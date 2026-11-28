(() => {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const filePills = document.getElementById("filePills");
  const compressBtn = document.getElementById("compressBtn");
  const zipBundleBtn = document.getElementById("zipBundleBtn");
  const clearBtn = document.getElementById("clearBtn");
  const downloadAllBtn = document.getElementById("downloadAllBtn");
  const statusText = document.getElementById("statusText");
  const resultsDiv = document.getElementById("results");
  const sliderBox = document.getElementById("sliderBox");
  const sliderMeta = document.getElementById("sliderMeta");
  const sliderMinLabel = document.getElementById("sliderMinLabel");
  const sizeSlider = document.getElementById("sizeSlider");
  const sliderReadout = document.getElementById("sliderReadout");
  const useSliderToggle = document.getElementById("useSliderToggle");
  const imageFormatSelect = document.getElementById("imageFormat");
  const maxWidthInput = document.getElementById("maxWidth");

  const IMAGE_EXTS = new Set(["jpg", "jpeg", "png", "webp", "avif", "bmp"]);
  const OFFICE_EXTS = new Set(["docx", "pptx", "xlsx", "odt", "odp", "ods"]);
  const OFFICE_MEDIA_PREFIXES = ["word/media/", "ppt/media/", "xl/media/", "Pictures/"];
  const PRESET_QUALITY = { low: 0.9, medium: 0.75, high: 0.52 };
  const OFFICE_PRESETS = {
    low: { maxDim: 1920, quality: 0.85 },
    medium: { maxDim: 1280, quality: 0.7 },
    high: { maxDim: 800, quality: 0.5 },
  };

  let queue = [];
  let compressedOutputs = [];

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let val = bytes / 1024;
    let idx = 0;
    while (val >= 1024 && idx < units.length - 1) {
      val /= 1024;
      idx++;
    }
    return `${val.toFixed(2)} ${units[idx]}`;
  }

  function parseTargetSpec(raw, origBytes) {
    const cleaned = (raw || "").trim().toUpperCase();
    if (!cleaned) return null;
    if (cleaned.endsWith("%")) {
      const pct = parseFloat(cleaned.slice(0, -1).trim());
      if (Number.isNaN(pct) || pct < 1 || pct > 100) {
        throw new Error(`Invalid percentage "${raw}". Use 1% to 100%.`);
      }
      return Math.max(1, Math.floor(origBytes * (pct / 100)));
    }
    const match = cleaned.match(/^(\d+(?:\.\d+)?)\s*(B|KB|K|MB|M|GB|G)?$/);
    if (!match) throw new Error(`Invalid target size "${raw}". Try 300KB, 1.5MB, or 45%.`);
    const val = parseFloat(match[1]);
    const unit = match[2] || "B";
    const mult = { B: 1, K: 1024, KB: 1024, M: 1048576, MB: 1048576, G: 1073741824, GB: 1073741824 };
    return Math.floor(val * mult[unit]);
  }

  function splitName(name) {
    const idx = name.lastIndexOf(".");
    if (idx <= 0) return { stem: name, ext: "" };
    return { stem: name.slice(0, idx), ext: name.slice(idx + 1).toLowerCase() };
  }

  function canvasToBlob(canvas, mime, quality) {
    return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), mime, quality));
  }

  async function encodeImageBlob(bitmap, targetFmt, quality, maxWidth) {
    const ratio = maxWidth && bitmap.width > maxWidth ? maxWidth / bitmap.width : 1;
    const width = Math.max(1, Math.round(bitmap.width * ratio));
    const height = Math.max(1, Math.round(bitmap.height * ratio));

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");

    if (targetFmt === "jpeg" || targetFmt === "jpg") {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, height);
    }
    ctx.drawImage(bitmap, 0, 0, width, height);

    const mimeMap = {
      jpg: "image/jpeg",
      jpeg: "image/jpeg",
      png: "image/png",
      webp: "image/webp",
      avif: "image/avif",
      bmp: "image/png",
    };
    let mime = mimeMap[targetFmt] || "image/jpeg";
    let blob = await canvasToBlob(canvas, mime, quality);

    if ((!blob || (mime === "image/avif" && blob.type !== "image/avif")) && targetFmt === "avif") {
      mime = "image/webp";
      blob = await canvasToBlob(canvas, mime, quality);
      return { blob, actualExt: "webp", fallbackNote: " (AVIF encode unsupported by browser, used WebP)" };
    }
    return { blob, actualExt: targetFmt === "bmp" ? "png" : targetFmt, fallbackNote: "" };
  }

  async function compressImageFile(file, ext, preset, requestedFmt, maxWidth, targetBytes) {
    const targetFmt = requestedFmt === "keep" ? (ext === "bmp" ? "png" : ext) : requestedFmt;
    const bitmap = await createImageBitmap(file);
    const baseQ = PRESET_QUALITY[preset];

    let bestBlob = null;
    let outExt = targetFmt;
    let engineNote = "";

    try {
      if (!targetBytes) {
        const encoded = await encodeImageBlob(bitmap, targetFmt, baseQ, maxWidth);
        bestBlob = encoded.blob;
        outExt = encoded.actualExt;
        engineNote = encoded.fallbackNote;
      } else {
        const qSteps = [baseQ, 0.65, 0.5, 0.35, 0.22];
        const scales = [1.0, 0.8, 0.65, 0.45];
        let met = false;
        for (const scale of scales) {
          const scaledW = Math.max(16, Math.round((maxWidth ? Math.min(bitmap.width, maxWidth) : bitmap.width) * scale));
          for (const q of qSteps) {
            const encoded = await encodeImageBlob(bitmap, targetFmt, q, scaledW);
            outExt = encoded.actualExt;
            engineNote = encoded.fallbackNote;
            if (!bestBlob || encoded.blob.size < bestBlob.size) {
              bestBlob = encoded.blob;
            }
            if (encoded.blob.size <= targetBytes) {
              bestBlob = encoded.blob;
              met = true;
              break;
            }
          }
          if (met) break;
        }
      }
    } finally {
      bitmap.close();
    }

    const allowKeep = requestedFmt === "keep" && !maxWidth;
    if (allowKeep && bestBlob.size >= file.size) {
      return { blob: file, outExt: ext, engine: "kept original (already optimal)", skippedLarger: true };
    }
    return { blob: bestBlob, outExt, engine: `canvas/${outExt}${engineNote}`, skippedLarger: false };
  }

  function optimizeSvgText(svgText, preset) {
    let out = svgText
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<metadata[\s\S]*?<\/metadata>/gi, "")
      .replace(/<(?:sodipodi|inkscape):[^>]*\/>/gi, "")
      .replace(/<(?:sodipodi|inkscape):[\s\S]*?<\/(?:sodipodi|inkscape):[^>]*>/gi, "")
      .replace(/\s+(?:inkscape|sodipodi|xmlns:(?:inkscape|sodipodi|dc|cc|rdf)):[A-Za-z0-9_-]+="[^"]*"/gi, "");

    const decimals = preset === "high" ? 1 : preset === "medium" ? 2 : 3;
    out = out.replace(/(\d+\.\d{4,})/g, (m) => Number(parseFloat(m).toFixed(decimals)).toString());
    out = out.replace(/>\s+</g, "><").replace(/\s{2,}/g, " ").trim();
    return out;
  }

  async function compressSvgFile(file, preset) {
    const raw = await file.text();
    const optimized = optimizeSvgText(raw, preset);
    const blob = new Blob([optimized], { type: "image/svg+xml" });
    if (blob.size >= file.size) {
      return { blob: file, outExt: "svg", engine: "kept original (already optimal)", skippedLarger: true };
    }
    return { blob, outExt: "svg", engine: `browser-svg/${preset}`, skippedLarger: false };
  }

  async function packOfficeAttempt(file, ext, cfg, level) {
    const zip = await JSZip.loadAsync(file);
    const isOffice = OFFICE_EXTS.has(ext);
    let optimizedImages = 0;

    if (isOffice) {
      const entries = Object.keys(zip.files);
      for (const entryName of entries) {
        const entry = zip.files[entryName];
        if (entry.dir) continue;
        const { ext: imgExt } = splitName(entryName);
        const inMedia = OFFICE_MEDIA_PREFIXES.some((prefix) => entryName.startsWith(prefix));
        if (!inMedia || !["jpg", "jpeg", "png", "webp", "bmp"].includes(imgExt)) continue;

        const origBytes = await entry.async("uint8array");
        const imgBlob = new Blob([origBytes]);
        try {
          const bitmap = await createImageBitmap(imgBlob);
          const encoded = await encodeImageBlob(bitmap, imgExt === "bmp" ? "png" : imgExt, cfg.quality, cfg.maxDim);
          bitmap.close();
          if (encoded.blob && encoded.blob.size < origBytes.byteLength) {
            zip.file(entryName, encoded.blob, { compression: "DEFLATE", compressionOptions: { level: 9 } });
            optimizedImages++;
          }
        } catch {
          // Leave unreadable embedded entry untouched
        }
      }
    }

    const outBlob = await zip.generateAsync({
      type: "blob",
      compression: "DEFLATE",
      compressionOptions: { level },
    });
    return { outBlob, isOffice, optimizedImages };
  }

  async function compressZipOrOffice(file, ext, preset, targetBytes = null) {
    if (typeof JSZip === "undefined") {
      throw new Error("JSZip failed to load from CDN. Please verify your internet connection.");
    }
    const level = preset === "low" ? 6 : 9;
    const isOffice = OFFICE_EXTS.has(ext);
    let best = null;

    if (isOffice && targetBytes) {
      const steps = [
        OFFICE_PRESETS[preset],
        { maxDim: 1280, quality: 0.7 },
        { maxDim: 960, quality: 0.52 },
        { maxDim: 640, quality: 0.35 },
      ];
      for (const cfg of steps) {
        const res = await packOfficeAttempt(file, ext, cfg, 9);
        if (!best || res.outBlob.size < best.outBlob.size) {
          best = res;
        }
        if (res.outBlob.size <= targetBytes) {
          best = res;
          break;
        }
      }
    } else {
      best = await packOfficeAttempt(file, ext, OFFICE_PRESETS[preset], level);
    }

    if (best.outBlob.size >= file.size) {
      return { blob: file, outExt: ext, engine: "kept original (already optimal)", skippedLarger: true };
    }
    const engine = best.isOffice
      ? `jszip/office (${best.optimizedImages} media img)`
      : `jszip/deflate-${level}`;
    return { blob: best.outBlob, outExt: ext, engine, skippedLarger: false };
  }

  function syncFormatControlAvailability() {
    if (!queue.length) {
      imageFormatSelect.disabled = false;
      return;
    }
    const hasConvertibleImage = queue.some((f) => IMAGE_EXTS.has(splitName(f.name).ext));
    if (!hasConvertibleImage) {
      imageFormatSelect.value = "keep";
      imageFormatSelect.disabled = true;
    } else {
      imageFormatSelect.disabled = false;
    }
  }

  function renderQueue() {
    filePills.innerHTML = "";
    queue.forEach((f, idx) => {
      const el = document.createElement("div");
      el.className = "pill";
      const label = document.createElement("span");
      label.textContent = `${f.name} (${formatBytes(f.size)})`;
      const btn = document.createElement("button");
      btn.title = "Remove";
      btn.innerHTML = "&times;";
      btn.onclick = () => {
        queue.splice(idx, 1);
        renderQueue();
      };
      el.append(label, btn);
      filePills.appendChild(el);
    });
    const empty = queue.length === 0;
    compressBtn.disabled = empty;
    zipBundleBtn.disabled = empty;
    clearBtn.disabled = empty;
    syncFormatControlAvailability();
    refreshSliderEstimate();
  }

  let activeOrigBytes = 0;
  let activeMinBytes = 0;

  function updateSliderReadout() {
    if (!activeOrigBytes) return;
    const pct = parseInt(sizeSlider.value, 10);
    const estBytes = Math.max(activeMinBytes, Math.floor(activeOrigBytes * (pct / 100)));
    const savedPct = Math.max(0, 100 - pct);
    sliderReadout.textContent = `Target: ${pct}% of original (~${formatBytes(estBytes)} • ${savedPct}% reduction)`;
  }

  async function probeFileMinimum(file, requestedFmt, maxWidth) {
    const { ext } = splitName(file.name);
    if (IMAGE_EXTS.has(ext)) {
      const targetFmt = requestedFmt === "keep" ? (ext === "bmp" ? "png" : ext) : requestedFmt;
      const bitmap = await createImageBitmap(file);
      try {
        const baseW = maxWidth ? Math.min(bitmap.width, maxWidth) : bitmap.width;
        const minW = Math.max(16, Math.round(baseW * 0.4));
        const encoded = await encodeImageBlob(bitmap, targetFmt, 0.18, minW);
        return Math.min(file.size, encoded.blob.size);
      } finally {
        bitmap.close();
      }
    }
    if (ext === "svg") {
      const res = await compressSvgFile(file, "high");
      return res.blob.size;
    }
    if (ext === "zip" || OFFICE_EXTS.has(ext)) {
      const res = await compressZipOrOffice(file, ext, "high");
      return res.blob.size;
    }
    return file.size;
  }

  async function refreshSliderEstimate() {
    if (queue.length !== 1) {
      sliderBox.hidden = true;
      useSliderToggle.checked = false;
      activeOrigBytes = 0;
      activeMinBytes = 0;
      return;
    }
    const file = queue[0];
    const { ext } = splitName(file.name);
    if (!IMAGE_EXTS.has(ext) && ext !== "svg" && ext !== "zip" && !OFFICE_EXTS.has(ext)) {
      sliderBox.hidden = true;
      useSliderToggle.checked = false;
      return;
    }

    sliderBox.hidden = false;
    sliderMeta.textContent = `Checking smallest possible size for ${file.name}...`;
    const requestedFmt = imageFormatSelect.value;
    const maxWRaw = maxWidthInput.value.trim();
    const maxWidth = maxWRaw ? parseInt(maxWRaw, 10) : null;

    try {
      const minBytes = Math.max(1, await probeFileMinimum(file, requestedFmt, maxWidth));
      if (queue[0] !== file) return;
      activeOrigBytes = file.size;
      activeMinBytes = minBytes;
      const minPct = Math.max(1, Math.min(100, Math.ceil((minBytes / file.size) * 100)));
      sizeSlider.min = String(minPct);
      sizeSlider.max = "100";
      sizeSlider.value = String(Math.floor((minPct + 100) / 2));
      sliderMinLabel.textContent = `${minPct}% min`;
      sliderMeta.textContent = `Original: ${formatBytes(file.size)} • Smallest possible: ${formatBytes(minBytes)} (${minPct}% of original, up to ${100 - minPct}% smaller)`;
      useSliderToggle.checked = minPct < 100;
      updateSliderReadout();
    } catch {
      sliderBox.hidden = true;
    }
  }

  sizeSlider.addEventListener("input", () => {
    useSliderToggle.checked = true;
    updateSliderReadout();
  });
  imageFormatSelect.addEventListener("change", refreshSliderEstimate);
  maxWidthInput.addEventListener("change", refreshSliderEstimate);

  function addFiles(fileList) {
    for (const f of fileList) queue.push(f);
    renderQueue();
    statusText.textContent = `${queue.length} file(s) queued`;
  }

  dropzone.onclick = () => fileInput.click();
  dropzone.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  };
  fileInput.onchange = () => {
    addFiles(fileInput.files);
    fileInput.value = "";
  };
  dropzone.ondragover = (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  };
  dropzone.ondragleave = () => dropzone.classList.remove("dragover");
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    addFiles(e.dataTransfer.files);
  };

  clearBtn.onclick = () => {
    queue = [];
    compressedOutputs = [];
    resultsDiv.innerHTML = "";
    downloadAllBtn.style.display = "none";
    statusText.textContent = "Ready — select or drop files to begin";
    renderQueue();
  };

  function appendResultCard(origName, outputName, origSize, newSize, engine, skippedLarger, blob) {
    const url = URL.createObjectURL(blob);
    compressedOutputs.push({ name: outputName, blob });

    const card = document.createElement("div");
    card.className = "result-card";
    const meta = document.createElement("div");
    meta.className = "result-meta";

    const title = document.createElement("h3");
    title.textContent = outputName;

    const saved = origSize - newSize;
    const pct = origSize ? ((saved / origSize) * 100).toFixed(1) : "0.0";
    const summary = document.createElement("p");
    const badge = document.createElement("span");
    if (skippedLarger) {
      badge.className = "kept-badge";
      badge.textContent = "kept original";
    } else {
      badge.className = "saved-badge";
      badge.textContent = `-${pct}% (${formatBytes(saved)} saved)`;
    }
    summary.append(`${origName}: ${formatBytes(origSize)} → ${formatBytes(newSize)} `, badge, ` • ${engine}`);
    meta.append(title, summary);

    const link = document.createElement("a");
    link.className = "btn btn-emerald";
    link.href = url;
    link.download = outputName;
    link.textContent = "Download";

    card.append(meta, link);
    resultsDiv.appendChild(card);
  }

  function appendErrorCard(fileName, message) {
    const card = document.createElement("div");
    card.className = "error-card";
    card.textContent = `${fileName}: ${message}`;
    resultsDiv.appendChild(card);
  }

  zipBundleBtn.onclick = async () => {
    if (!queue.length || typeof JSZip === "undefined") return;
    zipBundleBtn.disabled = true;
    statusText.textContent = "Bundling files into compressed ZIP...";
    resultsDiv.innerHTML = "";
    compressedOutputs = [];

    try {
      const zip = new JSZip();
      let totalBytes = 0;
      for (const f of queue) {
        totalBytes += f.size;
        zip.file(f.name, f, { compression: "DEFLATE", compressionOptions: { level: 9 } });
      }
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 9 } });
      appendResultCard(`${queue.length} files`, "compressed_bundle.zip", totalBytes, blob.size, "jszip/deflate-9", false, blob);
      statusText.textContent = "ZIP bundle ready!";
    } catch (err) {
      appendErrorCard("Bundle", err.message);
      statusText.textContent = "Failed to bundle ZIP.";
    } finally {
      zipBundleBtn.disabled = queue.length === 0;
    }
  };

  downloadAllBtn.onclick = async () => {
    if (!compressedOutputs.length || typeof JSZip === "undefined") return;
    const zip = new JSZip();
    compressedOutputs.forEach((item) => zip.file(item.name, item.blob));
    const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE", compressionOptions: { level: 6 } });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "compressed_files.zip";
    a.click();
  };

  compressBtn.onclick = async () => {
    if (!queue.length) return;
    compressBtn.disabled = true;
    downloadAllBtn.style.display = "none";
    resultsDiv.innerHTML = "";
    compressedOutputs = [];

    const rawTarget = document.getElementById("targetSize").value.trim();
    const preset = document.getElementById("preset").value;
    const requestedFmt = imageFormatSelect.value;
    const maxWRaw = maxWidthInput.value.trim();
    const maxWidth = maxWRaw ? parseInt(maxWRaw, 10) : null;

    statusText.textContent = `Compressing ${queue.length} file(s) locally...`;
    let okCount = 0;
    let errCount = 0;

    for (const file of queue) {
      const { stem, ext } = splitName(file.name);
      let fileTargetBytes = null;
      try {
        if (useSliderToggle.checked && !rawTarget && queue.length === 1) {
          const sliderPct = parseInt(sizeSlider.value, 10);
          fileTargetBytes = Math.max(1, Math.floor(file.size * (sliderPct / 100)));
        } else if (rawTarget) {
          fileTargetBytes = parseTargetSpec(rawTarget, file.size);
        }

        let out;
        if (IMAGE_EXTS.has(ext)) {
          out = await compressImageFile(file, ext, preset, requestedFmt, maxWidth, fileTargetBytes);
        } else if (ext === "svg") {
          out = await compressSvgFile(file, preset);
        } else if (ext === "zip" || OFFICE_EXTS.has(ext)) {
          out = await compressZipOrOffice(file, ext, preset, fileTargetBytes);
        } else {
          throw new Error(
            `".${ext}" runs via the Python CLI or Codespaces terminal — or click "Bundle as .zip" right above.`
          );
        }
        const outName = `${stem}_compressed.${out.outExt}`;
        appendResultCard(file.name, outName, file.size, out.blob.size, out.engine, out.skippedLarger, out.blob);
        okCount++;
      } catch (err) {
        appendErrorCard(file.name, err.message);
        errCount++;
      }
    }

    if (compressedOutputs.length > 1 && typeof JSZip !== "undefined") {
      downloadAllBtn.style.display = "inline-flex";
    }
    statusText.textContent = `Done: ${okCount} compressed locally, ${errCount} skipped/error.`;
    compressBtn.disabled = queue.length === 0;
  };

  // Copy helper for CLI snippets
  document.querySelectorAll("[data-copy]").forEach((el) => {
    el.addEventListener("click", async () => {
      const text = el.getAttribute("data-copy");
      if (!text || !navigator.clipboard) return;
      try {
        await navigator.clipboard.writeText(text);
        const orig = el.textContent;
        if (el.classList.contains("copy-btn")) {
          el.textContent = "Copied!";
          setTimeout(() => { el.textContent = orig; }, 1200);
        } else {
          statusText.textContent = `Copied CLI command: ${text}`;
        }
      } catch {
        // Clipboard unavailable in restricted contexts
      }
    });
  });
})();
