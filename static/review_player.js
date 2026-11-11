'use strict';

(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ClipifyReviewPlayer = api;
})(typeof globalThis === 'undefined' ? this : globalThis, function () {
  function errorMessage(video) {
    const code = video?.error?.code;
    if (code === 1) return 'Video loading was interrupted. Select the Short again to retry.';
    if (code === 2) return 'The saved Short could not be fetched. Check the project and try again.';
    if (code === 3) return 'This browser could not decode the saved Short.';
    if (code === 4) return 'This saved Short uses a video format this browser cannot play.';
    return 'The saved Short could not be loaded. Try reopening the project.';
  }

  function attach(video, status, spinner, statusText) {
    if (!video || !status || !spinner || !statusText) return null;

    const show = (message, loading) => {
      statusText.textContent = message;
      spinner.hidden = !loading;
      status.dataset.state = loading ? 'loading' : 'error';
      status.hidden = !message;
    };
    const clear = () => show('', false);
    const onLoadStart = () => show('Loading video…', true);
    const onLoadedData = () => clear();
    const onWaiting = () => show('Buffering video…', true);
    const onError = () => show(errorMessage(video), false);

    video.addEventListener('loadstart', onLoadStart);
    video.addEventListener('loadeddata', onLoadedData);
    video.addEventListener('canplay', onLoadedData);
    video.addEventListener('playing', onLoadedData);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('error', onError);

    return {
      load(src) {
        if (!src) {
          show('No video was selected.', false);
          return;
        }
        video.pause();
        video.hidden = false;
        show('Loading video…', true);
        video.src = src;
        video.load();
      },
      clear,
    };
  }

  return { attach, errorMessage };
});
