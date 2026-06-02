
const MenuModule = {
    callback: null,
    isLoaded: false,
    currentRoute: null,
    isInitialized: false,
    routesDescriptions: {}, // { "id-m": { name, description, id, m } }
    _isFetchingRoutes: false,

    // URL Яндекс-функции для загрузки маршрутов (общий бекенд)
    API_URL_V2: 'https://functions.yandexcloud.net/d4e6qbc1mm9j44h0na3n',
    API_URL_V3: 'https://functions.yandexcloud.net/d4gpc1s9gqfohfa8c63d', // Новый URL для API v3
    
    /**
     * Получить правильный URL API в зависимости от версии
     */
    getApiUrl() {
        return this.API_URL_V2;
    },

    /**
     * Универсальное получение параметров URL
     * Поддерживает только формат: #m=id-название
     */
    getUrlParam(name) {
        if (name !== 'm') return null;

        // Проверка query-строки URL
        let value = new URLSearchParams(window.location.search).get(name);
        if (value) return value;

        // Проверка hash: #m=id-название
        const hash = window.location.hash.slice(1);
        if (hash) {
            // Формат: #m=id-название
            const hashParams = new URLSearchParams(hash);
            value = hashParams.get(name);
            if (value) return value;

            // Формат: #/path?m=id-название
            const hashQueryIndex = hash.indexOf('?');
            if (hashQueryIndex > -1) {
                const hashQuery = hash.substring(hashQueryIndex + 1);
                const hashQueryParams = new URLSearchParams(hashQuery);
                value = hashQueryParams.get(name);
                if (value) return value;
            }
        }

        return null;
    },

    /**
     * Парсинг ввода в формате "id-название"
     * @returns {{id: string, name: string}}
     */
    parseRouteInput(input) {
        const trimmed = input.trim();
        const dashIndex = trimmed.indexOf('-');
        
        if (dashIndex > 0) {
            const id = trimmed.substring(0, dashIndex).trim();
            const name = trimmed.substring(dashIndex + 1).trim();
            return { id, name };
        }
        if (/^\d+$/.test(trimmed)) {
            return { id: trimmed, name: '' };
        }
        return { id: '', name: trimmed };
    },

    // Инициализация
    async init(onRouteLoaded) {
        this.callback = onRouteLoaded;
        this.createModal();
        this.createButton();
        this.hide();

        // Загружаем список маршрутов динамически
        await this._loadRoutesList();

        // Проверяем параметры сразу и при получении данных от VK Bridge
        this.checkUrlParam();

        // Подписка на события VK Bridge для параметров запуска
        if (typeof vkBridge !== 'undefined') {
            vkBridge.subscribe((event) => {
                // Проверяем, что маршрут ещё не загружен
                if (!this.isLoaded && (event && event.type === 'VKWebAppUpdateConfig' || event.detail)) {
                    this.checkUrlParam();
                }
            });

            // Пробуем получить параметры из launchParams
            try {
                vkBridge.send('VKWebAppGetLaunchParams')
                    .then(params => {
                        // Проверяем, что маршрут ещё не загружен
                        if (!this.isLoaded && params && params.m) {
                            const { id, name } = this.parseRouteInput(params.m);
                            if (name) {
                                this.isLoaded = true;
                                this.hide();
                                this.loadRouteByName(name, id);
                            } else if (id) {
                                this.currentRoute = id;
                            }
                        }
                    })
                    .catch(e => {});
            } catch (e) {
            }
        }

        // Проверка start_param от Telegram Mini App
        if (typeof Telegram !== 'undefined' && Telegram.WebApp) {
            try {
                const startParam = Telegram.WebApp.initDataUnsafe?.start_param;
                if (startParam && startParam.startsWith('m=') && !this.isLoaded) {
                    const mValue = startParam.substring(2);
                    const { id, name } = this.parseRouteInput(mValue);
                    if (name) {
                        this.isLoaded = true;
                        this.hide();
                        this.loadRouteByName(name, id);
                    } else if (id) {
                        this.currentRoute = id;
                    }
                }
            } catch (e) {
            }
        }

        this.isInitialized = true;
    },

    /**
     * Загрузка списка маршрутов из Яндекс-функции
     */
    async _loadRoutesList() {
        // Защита от одновременных запросов
        if (this._isFetchingRoutes) return;
        this._isFetchingRoutes = true;
        
        try {
            const routes = await this._fetchFromAPI();
            this._buildRoutesList(routes);
        } catch (e) {
            console.warn('Не удалось загрузить список маршрутов:', e);
            const container = document.getElementById('routesListContainer');
            if (container) {
                container.innerHTML = `
                    <div style="text-align:center; padding:20px; color:rgba(255,100,100,0.8); font-size:14px;">
                        Не удалось загрузить список маршрутов.<br>
                        <small>Введите ID и название вручную</small>
                    </div>
                `;
            }
        } finally {
            this._isFetchingRoutes = false;
        }
    },

    /**
     * Запрос к Яндекс-функции за списком маршрутов
     */
    async _fetchFromAPI() {
        const url = `${this.getApiUrl()}?action=list_routes`;
        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // Группировка по категориям
        const routesByCategory = {};
        const routesFlat = {};
        
        for (const route of data) {
            const category = route.category || 'Без категории';
            const key = `${route.id}-${route.m}`;
            
            // Сохраняем для flat доступа
            routesFlat[key] = {
                id: route.id,
                m: route.m,
                name: route.name,
                category: category,
                description: route.description || ''
            };
            
            // Группируем по категориям
            if (!routesByCategory[category]) {
                routesByCategory[category] = [];
            }
            routesByCategory[category].push({ key, ...routesFlat[key] });
        }

        // Сортируем категории и маршруты
        const sortedCategories = Object.keys(routesByCategory).sort();
        const sortedRoutesByCategory = {};
        for (const cat of sortedCategories) {
            sortedRoutesByCategory[cat] = routesByCategory[cat].sort((a, b) => a.name.localeCompare(b.name));
        }

        this.routesDescriptions = routesFlat;
        this.routesByCategory = sortedRoutesByCategory;
        
        return sortedRoutesByCategory;
    },

    /**
     * Построение HTML списка маршрутов с группировкой по категориям
     */
    _buildRoutesList(routesByCategory) {
        if (!routesByCategory) return;

        const container = document.getElementById('routesListContainer');
        if (!container) return;

        const categories = Object.keys(routesByCategory);

        let hasVisible = false;
        let html = '';

        for (const category of categories) {
            const routes = routesByCategory[category];
            if (!routes || routes.length === 0) continue;
            hasVisible = true;

            html += `
                <div class="category-folder" onclick="event.stopPropagation();MenuModule.openCategory('${this._escape(category)}')">
                    <div class="category-header">
                        <span class="category-icon">📁</span>
                        <span class="category-name">${category}</span>
                        <span class="category-count">${routes.length}</span>
                        <span class="category-arrow">›</span>
                    </div>
                </div>
            `;
        }

        if (!hasVisible) {
            container.innerHTML = `
                <div style="text-align:center; padding:20px; color:rgba(255,255,255,0.5); font-size:14px;">
                    Нет доступных маршрутов
                </div>
            `;
            return;
        }

        container.innerHTML = html;
    },

    /**
     * Показать маршруты внутри категории
     */
    openCategory(categoryName) {
        const routes = this.routesByCategory[categoryName];
        if (!routes || routes.length === 0) {
            const container = document.getElementById('routesListContainer');
            if (container) {
                container.innerHTML = `
                    <div class="category-title" style="display:flex;align-items:center;gap:10px;padding:12px 16px;margin-bottom:8px;background:rgba(0,122,255,0.1);border-radius:12px;border:1px solid rgba(0,122,255,0.2);">
                        <button class="back-btn" onclick="event.stopPropagation();MenuModule.showCategories()" style="display:flex;align-items:center;gap:6px;padding:10px 14px;border-radius:12px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.8);font-size:14px;font-weight:600;cursor:pointer;flex-shrink:0;width:auto;margin:0;">
                            <span>‹</span> Назад
                        </button>
                        <span class="category-icon">📁</span>
                        <span style="flex:1;font-size:18px;font-weight:700;">${categoryName}</span>
                    </div>
                    <div style="text-align:center; padding:20px; color:rgba(255,255,255,0.5); font-size:14px;">
                        Нет маршрутов в этой категории
                    </div>
                `;
            }
            return;
        }

        const container = document.getElementById('routesListContainer');

        let html = `
            <div class="category-title" style="display:flex;align-items:center;gap:10px;padding:12px 16px;margin-bottom:8px;background:rgba(0,122,255,0.1);border-radius:12px;border:1px solid rgba(0,122,255,0.2);">
                <button class="back-btn" onclick="event.stopPropagation();MenuModule.showCategories()" style="display:flex;align-items:center;gap:6px;padding:10px 14px;border-radius:12px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.8);font-size:14px;font-weight:600;cursor:pointer;flex-shrink:0;width:auto;margin:0;">
                    <span>‹</span> Назад
                </button>
                <span class="category-icon">📁</span>
                <span style="flex:1;font-size:18px;font-weight:700;">${categoryName}</span>
            </div>
        `;

        for (const route of routes) {
            const routeKey = route.key;
            const hasDesc = route.description && route.description.trim() !== '';
            const isActive = routeKey === this.currentRoute;
            html += `<button class="route-item${isActive ? ' active' : ''}" onclick="event.stopPropagation();MenuModule.selectRoute('${route.key}')"${isActive ? ' style="background:rgba(48,209,88,0.2);border-color:rgba(48,209,88,0.4);"' : ''}>
                <span class="route-name">${route.name}</span>
                ${hasDesc ? `<span class="route-info-btn" onclick="event.stopPropagation();MenuModule._showRouteDescription('${routeKey}')">?</span>` : ''}
            </button>`;
        }

        container.innerHTML = html;
    },

    /**
     * Показать все категории
     */
    showCategories() {
        this._buildRoutesList(this.routesByCategory);
    },

    /**
     * Выбрать маршрут
     */
    selectRoute(routeKey) {
        const route = this.routesDescriptions[routeKey];
        if (route) {
            this.loadRouteByName(route.m, route.id);
        }
    },

    _escape(str) {
        return str.replace(/'/g, "\\'");
    },

    /**
     * Показать описание маршрута
     */
    _showRouteDescription(routeKey) {
        const routeData = this.routesDescriptions[routeKey];
        if (!routeData || !routeData.description) return;

        // Создаём модальное окно если его нет
        let descModal = document.getElementById('routeDescModal');
        if (!descModal) {
            descModal = document.createElement('div');
            descModal.id = 'routeDescModal';
            descModal.innerHTML = `
                <div class="desc-modal-overlay" id="routeDescOverlay">
                    <div class="desc-modal-content">
                        <div class="desc-modal-header">
                            <span id="routeDescTitle"></span>
                            <button id="routeDescCloseBtn" class="desc-close-btn">×</button>
                        </div>
                        <div class="desc-modal-body" id="routeDescText"></div>
                    </div>
                </div>
            `;
            document.body.appendChild(descModal);

            // Закрытие по клику на overlay
            document.getElementById('routeDescOverlay').addEventListener('click', (e) => {
                if (e.target === e.currentTarget) {
                    this._hideRouteDescription();
                }
            });

            // Закрытие по кнопке
            document.getElementById('routeDescCloseBtn').addEventListener('click', () => {
                this._hideRouteDescription();
            });
        }

        const routeData2 = this.routesDescriptions[routeKey];
        document.getElementById('routeDescTitle').textContent = routeData2.name;
        document.getElementById('routeDescText').textContent = routeData2.description;
        descModal.style.display = 'block';
        requestAnimationFrame(() => descModal.classList.add('visible'));
    },

    /**
     * Скрыть описание маршрута
     */
    _hideRouteDescription() {
        const descModal = document.getElementById('routeDescModal');
        if (descModal) {
            descModal.classList.remove('visible');
            setTimeout(() => descModal.style.display = 'none', 300);
        }
    },
    
    // Создание модального окна
    createModal() {
        const html = `
            <div id="jsonModal">
                <div class="modal-sheet">
                    <div id="routesListContainer" class="routes-list">
                        <div style="text-align:center; padding:20px; color:rgba(255,255,255,0.5); font-size:14px;">
                            Загрузка списка маршрутов...
                        </div>
                    </div>
                </div>
            </div>
            <div id="loadingSpinner">
                <div class="spinner-box">
                    <div class="spinner-ring"></div>
                    <div class="spinner-text">Загрузка маршрута...</div>
                </div>
            </div>
        `;

        const loading = document.getElementById('loading');
        if (loading) {
            loading.insertAdjacentHTML('afterend', html);
        } else {
            document.body.insertAdjacentHTML('afterbegin', html);
        }

        // Закрытие при клике на фон (вне modal-sheet)
        document.getElementById('jsonModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('jsonModal')) {
                this.hide();
            }
        });

        // Закрытие при клике на любую кнопку приложения (кроме кнопки меню и модалки описания)
        document.addEventListener('click', (e) => {
            const descModal = document.getElementById('routeDescModal');
            if (descModal && descModal.style.display === 'block') {
                const descOverlay = document.getElementById('routeDescOverlay');
                if (descOverlay && descOverlay.contains(e.target)) {
                    this._hideRouteDescription();
                    return;
                }
            }

            const modal = document.getElementById('jsonModal');
            if (modal && !modal.classList.contains('hidden')) {
                const sheet = modal.querySelector('.modal-sheet');
                const menuBtn = document.getElementById('menuBtn');
                const descModalEl = document.getElementById('routeDescModal');
                if (descModalEl && descModalEl.contains(e.target)) {
                    return; // Не закрываем меню если клик внутри модалки описания
                }
                if (sheet && !sheet.contains(e.target) && e.target !== menuBtn && !menuBtn.contains(e.target)) {
                    this.hide();
                }
            }
        });
    },
    
    // Создание кнопки меню
    createButton() {
        const html = `
            <button id="menuBtn" class="circle-btn">
                <span>Маршруты</span>
            </button>
        `;
        
        const container = document.getElementById('topCenterControls');
        if (container) {
            container.insertAdjacentHTML('afterbegin', html);
        } else {
            const loading = document.getElementById('loading');
            if (loading) {
                loading.insertAdjacentHTML('afterend', html);
            } else {
                document.body.insertAdjacentHTML('afterbegin', html);
            }
        }
        
        // Обработчик клика
        document.getElementById('menuBtn').addEventListener('click', () => {
            const modal = document.getElementById('jsonModal');
            if (modal && modal.classList.contains('hidden')) {
                this.show();
            } else {
                this.hide();
            }
        });
    },
    
    // Проверка URL параметра
    checkUrlParam() {
        const routeParam = this.getUrlParam('m');
        if (!routeParam) return;

        const { id, name } = this.parseRouteInput(routeParam);

        // Только ID, без названия — фильтруем список, не загружаем маршрут
        if (!name) {
            this.currentRoute = id;
            return;
        }

        // ID и название — загружаем маршрут
        this.currentRoute = routeParam;
        this.isLoaded = true;
        this.hide();
        this.loadRouteByName(name, id);
    },
    
    // Загрузка маршрута по названию (внутренний метод)
    async loadRouteByName(routeName, routeId = null) {
        this.showSpinner();
        try {
            this.currentRoute = routeId ? `${routeId}-${routeName}` : routeName;
            
            this.hide();
            
            let url = this.getApiUrl();
            const params = [];
            if (routeId) {
                params.push(`id=${encodeURIComponent(routeId)}`);
            }
            if (routeName) {
                params.push(`m=${encodeURIComponent(routeName)}`);
            }

            if (typeof vkBridge !== 'undefined') {
                try {
                    const userInfo = await Promise.race([
                        vkBridge.send('VKWebAppGetUserInfo'),
                        new Promise((_, reject) =>
                            setTimeout(() => reject(new Error('timeout')), 1000)
                        )
                    ]);
                    
                    if (userInfo) {
                        const city = userInfo.city?.title || 'не указан';
                        const fullName = [userInfo.first_name, userInfo.last_name].filter(Boolean).join(' ');
                        const userInfoStr = 'vk:' + [userInfo.id, fullName, city].join(',');
                        const userInfoBase64 = btoa(encodeURIComponent(userInfoStr));
                        params.push(`i=${userInfoBase64}`);
                    }
                } catch (e) {
                }
            }

            if (window.tgUser) {
                try {
                    const user = window.tgUser;
                    const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ');
                    const userInfoStr = 'tg:' + [user.id, fullName, user.username || ''].join(',');
                    const userInfoBase64 = btoa(encodeURIComponent(userInfoStr));
                    params.push(`i=${userInfoBase64}`);
                } catch (e) {
                }
            }

            params.push(`ua=${encodeURIComponent(navigator.userAgent)}`);
            try {
                const r = await fetch('https://api.ipify.org?format=json');
                if (r.ok) params.push(`ip=${encodeURIComponent((await r.json()).ip)}`);
            } catch {}

            try {
                const pos = await new Promise((resolve) => {
                    navigator.geolocation.getCurrentPosition(
                        p => resolve(p.coords),
                        () => resolve(null),
                        { enableHighAccuracy: false, timeout: 1, maximumAge: Infinity }
                    );
                });
                if (pos) {
                    params.push(`lat=${pos.latitude}&lon=${pos.longitude}`);
                }
            } catch {}

            if (params.length > 0) {
                url += '?' + params.join('&');
            }

            const res = await fetch(url);

            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();

            this.hideSpinner();
            this.loadRoute(data);
        } catch (e) {
            this.hideSpinner();
            console.error('[MenuModule] Ошибка загрузки маршрута:', e);
            if (typeof showToast === 'function') {
                showToast('Ошибка загрузки: ' + e.message, 'error', 5000);
            }
        }
    },

    // Загрузка маршрута (публичный метод, передаёт JSON в навигатор)
    loadRoute(jsonData) {
        // Очищаем предыдущий маршрут
        if (typeof clearRoute === 'function') {
            clearRoute();
        }
        
        // Передаём JSON данные в навигатор
        if (typeof this.callback === 'function') {
this.callback(jsonData);
        }
        this.isLoaded = true;
        this.hide();
    },
    
    // Скрыть модальное окно
    hide() {
        const modal = document.getElementById('jsonModal');
        if (modal) modal.classList.add('hidden');
        this._hideRouteDescription();
    },
    
    // Показать модальное окно
    show() {
        const modal = document.getElementById('jsonModal');
        if (modal) modal.classList.remove('hidden');
        this._hideRouteDescription();
        this._buildRoutesList(this.routesByCategory);
        if (this.currentRoute && this.routesDescriptions[this.currentRoute]) {
            const category = this.routesDescriptions[this.currentRoute].category || 'Без категории';
            this.openCategory(category);
        }
    },
    
    showSpinner() {
        const spinner = document.getElementById('loadingSpinner');
        if (spinner) spinner.classList.add('active');
    },

    hideSpinner() {
        const spinner = document.getElementById('loadingSpinner');
        if (spinner) spinner.classList.remove('active');
    }
};
