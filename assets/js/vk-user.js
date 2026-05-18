const VK = {
    getId() {
        return window.vkUser?.id || null;
    },

    getName() {
        const user = window.vkUser;
        if (!user) return null;
        return `${user.first_name || ''}${user.last_name ? ' ' + user.last_name : ''}`.trim();
    },

    isAuthorized() {
        return !!window.vkUser?.id;
    },

    init() {
        if (typeof vkBridge !== 'undefined') {
            vkBridge.send('VKWebAppInit');
            vkBridge.send('VKWebAppGetUserInfo').then(data => {
                window.vkUser = data;
            });
        }
    }
};
