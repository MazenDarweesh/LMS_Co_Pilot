/**
 * User Authorized Screens Discovery Script
 * Queries the Angular Host ERP runtime (window.DynamicERP) directly from browser memory
 * to retrieve the list of screens and modules authorized for the current logged-in user.
 */
(function() {
    try {
        if (window.DynamicERP && typeof window.DynamicERP.listUserPages === 'function') {
            return window.DynamicERP.listUserPages();
        }
        if (window.DynamicERP && typeof window.DynamicERP.listScreens === 'function') {
            return window.DynamicERP.listScreens();
        }
        return [];
    } catch (e) {
        return [];
    }
})()
