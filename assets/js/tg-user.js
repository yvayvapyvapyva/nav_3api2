const TG = {
    getId() {
        return window.tgUser?.id || null;
    },

    getName() {
        const user = window.tgUser;
        if (!user) return null;
        return [user.first_name, user.last_name].filter(Boolean).join(' ');
    },

    getUsername() {
        return window.tgUser?.username || '';
    },

    init() {
        if (typeof Telegram !== 'undefined' && Telegram.WebApp) {
            Telegram.WebApp.ready();
            Telegram.WebApp.expand();
            try { Telegram.WebApp.requestFullscreen?.(); } catch (e) {}
            try { Telegram.WebApp.disableVerticalSwipes?.(); } catch (e) {}
            const user = Telegram.WebApp.initDataUnsafe?.user;
            if (user) {
                window.tgUser = user;
            }
        }

    }
};
