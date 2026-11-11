'use strict';

(function (root, factory) {
  const api = factory();
  if (root) root.ClipifyDownloadWarning = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? null : window, function () {
  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let index = 0;
    while (value >= 1000 && index < units.length - 1) {
      value /= 1000;
      index += 1;
    }
    const digits = value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2;
    return `${value.toFixed(digits)} ${units[index]}`;
  }

  function positiveBytes(value) {
    const bytes = Number(value);
    return Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  }

  function selectedModelDownloadBytes(detection, selectedIds) {
    const models = Array.isArray((detection || {}).models) ? detection.models : [];
    return (Array.isArray(selectedIds) ? selectedIds : []).reduce((sum, id) => {
      const model = models.find((item) => item.id === id);
      return sum + (model && !model.installed ? positiveBytes(model.sizeBytes) : 0);
    }, 0);
  }

  function buildDownloadWarning(detection, options) {
    const facts = detection || {};
    const choice = options || {};
    const models = Array.isArray(facts.models) ? facts.models : [];
    const selectedIds = Array.isArray(choice.models) ? choice.models : [];
    const selectedModels = selectedIds
      .map((id) => models.find((model) => model.id === id))
      .filter((model) => model && !model.installed);
    const modelBytes = selectedModelDownloadBytes(facts, selectedIds);
    const runtimeBytes = choice.installRuntime ? positiveBytes(facts.runtimeBytes) : 0;
    const ollamaBytes = choice.installOllama ? positiveBytes(facts.ollamaBytes) : 0;
    const bytes = modelBytes + runtimeBytes + ollamaBytes;
    const details = [];

    if (selectedModels.length) {
      const names = selectedModels.map((model) => model.name || model.id).join(', ');
      details.push(`Selected models: ${names} (${formatBytes(modelBytes)} to download).`);
    }
    if (runtimeBytes) {
      details.push(`AI runtime: ${formatBytes(runtimeBytes)} to download, then prepare.`);
    }
    if (ollamaBytes) {
      details.push(`Ollama: ${formatBytes(ollamaBytes)} to download and install.`);
    }

    if (!bytes) {
      return {
        bytes: 0,
        title: 'Ready to install',
        body: 'No AI model, runtime, or Ollama downloads are required by these options. Only the application files will be installed.',
        estimate: 'No AI component downloads are planned. Application files still need to be copied.',
        details: [],
      };
    }

    const bestMinutes = Math.max(1, Math.round(bytes / (12 * 1e6) / 60));
    const worstMinutes = Math.max(bestMinutes, Math.round(bytes / (3 * 1e6) / 60));
    const time = bestMinutes === worstMinutes
      ? `about ${bestMinutes} minute${bestMinutes === 1 ? '' : 's'}`
      : `roughly ${bestMinutes}-${worstMinutes} minutes`;
    return {
      bytes,
      title: 'Before the download starts',
      body: 'Only the selected components below need downloading. Runtime preparation can add time after the download.',
      estimate: `About ${formatBytes(bytes)} of additional files need downloading. Network time is ${time} at 3-12 MB/s, plus any setup work.`,
      details,
    };
  }

  return { buildDownloadWarning, selectedModelDownloadBytes };
});
