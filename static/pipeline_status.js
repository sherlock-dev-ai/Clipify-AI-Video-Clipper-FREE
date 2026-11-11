(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ClipifyPipelineStatus = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const STEPS = Object.freeze([
    { name: 'transcribe', start: 0, completeAt: 34 },
    { name: 'analyze', start: 34, completeAt: 64 },
    { name: 'edit', start: 64, completeAt: 78 },
    { name: 'caption', start: 78, completeAt: 92 },
    { name: 'render', start: 92, completeAt: 100 },
  ]);

  function stepStates(progress, failed = false) {
    const pct = Math.max(0, Math.min(100, Number(progress) || 0));
    let current = STEPS.findIndex(step => pct < step.completeAt);
    if (current < 0 && failed) current = STEPS.length - 1;
    return STEPS.map((step, index) => ({
      name: step.name,
      state: index < current || (!failed && pct >= step.completeAt)
        ? 'complete'
        : failed && index === current
          ? 'failed'
          : !failed && index === current
            ? 'active'
            : 'pending',
    }));
  }

  function cleanFailure(message) {
    const text = String(message || 'The pipeline stopped before a Short was created.')
      .replace(/^\s*\[ERROR\]\s*/i, '')
      .replace(/\s+/g, ' ')
      .trim();
    return text || 'The pipeline stopped before a Short was created.';
  }

  return Object.freeze({ stepStates, cleanFailure });
});
