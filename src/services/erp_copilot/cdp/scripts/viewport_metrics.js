/**
 * Viewport Metrics & Windows DPI Scale Extractor
 * Reads innerWidth, innerHeight, devicePixelRatio (Windows display scaling), and scroll offsets.
 */
(function() {
    return {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        devicePixelRatio: window.devicePixelRatio || 1,
        scrollX: window.scrollX || 0,
        scrollY: window.scrollY || 0
    };
})()
