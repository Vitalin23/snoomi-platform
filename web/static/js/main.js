// web/static/js/main.js

// Глобальные функции
function showToast(type, title, message) {
    // Создаем контейнер для тостов, если его нет
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
        toastContainer.style.zIndex = '9999';
        document.body.appendChild(toastContainer);
    }
    
    // Создаем toast
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.id = toastId;
    toast.className = `toast fade show border-0`;
    toast.role = 'alert';
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    // Определяем цвет в зависимости от типа
    let bgColor, textColor;
    switch(type) {
        case 'success':
            bgColor = 'bg-success';
            textColor = 'text-white';
            break;
        case 'error':
        case 'danger':
            bgColor = 'bg-danger';
            textColor = 'text-white';
            break;
        case 'warning':
            bgColor = 'bg-warning';
            textColor = 'text-dark';
            break;
        default:
            bgColor = 'bg-info';
            textColor = 'text-white';
    }
    
    toast.innerHTML = `
        <div class="toast-header ${bgColor} ${textColor}">
            <strong class="me-auto">${title}</strong>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;
    
    toastContainer.appendChild(toast);
    
    // Автоматическое удаление через 5 секунд
    setTimeout(() => {
        const toastEl = document.getElementById(toastId);
        if (toastEl) {
            toastEl.remove();
        }
    }, 5000);
}

// Форматирование чисел
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

// Форматирование даты
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 60) {
        return `${diffMins} мин. назад`;
    } else if (diffHours < 24) {
        return `${diffHours} ч. назад`;
    } else if (diffDays < 7) {
        return `${diffDays} дн. назад`;
    } else {
        return date.toLocaleDateString('ru-RU', {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
        });
    }
}

// Проверка подключения
function checkConnection() {
    if (!navigator.onLine) {
        showToast('warning', 'Нет соединения', 'Проверьте подключение к интернету');
        return false;
    }
    return true;
}

// Сохранение в localStorage
function saveToStorage(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
        return true;
    } catch (e) {
        console.error('Ошибка сохранения в localStorage:', e);
        return false;
    }
}

// Загрузка из localStorage
function loadFromStorage(key, defaultValue = null) {
    try {
        const value = localStorage.getItem(key);
        return value ? JSON.parse(value) : defaultValue;
    } catch (e) {
        console.error('Ошибка загрузки из localStorage:', e);
        return defaultValue;
    }
}

// Валидация email
function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

// Валидация URL
function isValidUrl(url) {
    try {
        new URL(url);
        return true;
    } catch (_) {
        return false;
    }
}

// Копирование в буфер обмена
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('success', 'Скопировано', 'Текст скопирован в буфер обмена');
    }).catch(err => {
        console.error('Ошибка копирования:', err);
        showToast('error', 'Ошибка', 'Не удалось скопировать текст');
    });
}

// -------------------- Пошаговые подсказки (guided hints) --------------------
const GUIDE_DISABLED_KEY = 'snoomi_guide_disabled';
const GUIDE_SEEN_PREFIX = 'snoomi_guide_seen:';

const GUIDE_STEPS_BY_PATH = {
    '/channels': [
        {
            selector: '#autopostConnectCard',
            title: 'Шаг 1/5: Подключение',
            text: 'Здесь подключается канал: сначала ссылка/ник, затем проверка и сохранение.',
            placement: 'bottom'
        },
        {
            selector: '#autopostVerifyBtn',
            title: 'Шаг 2/5: Проверка канала',
            text: 'Сначала проверьте доступность канала. Без проверки сохранение заблокировано.',
            placement: 'left'
        },
        {
            selector: '#autopostDescription',
            title: 'Шаг 3/5: Описание для AI',
            text: 'Опишите интересы и боли аудитории (20+ слов), а не цели продаж компании.',
            placement: 'top'
        },
        {
            selector: '#autopostSubmitBtn',
            title: 'Шаг 4/5: Сохранение',
            text: 'После сохранения канал сразу попадет в контур автопостинга.',
            placement: 'top'
        },
        {
            selector: '#connectedChannelsCard',
            title: 'Шаг 5/5: Контроль',
            text: 'Проверяйте здесь, какие каналы уже подключены, и переходите к шагу 2.',
            placement: 'top'
        }
    ],
    '/posting-setup': [
        {
            selector: '#plannerChannelSelect',
            title: 'Шаг 1/4: Выбор канала',
            text: 'Выберите канал, для которого формируется список тем.',
            placement: 'right'
        },
        {
            selector: '#plannerGenerateBtn',
            title: 'Шаг 2/4: Генерация',
            text: 'Нажмите, чтобы получить темы и топ актуальных вопросов аудитории.',
            placement: 'right'
        },
        {
            selector: '#plannerTopicsContainer',
            title: 'Шаг 3/4: Редактирование',
            text: 'Отредактируйте формулировки тем перед сохранением.',
            placement: 'top'
        },
        {
            selector: '#plannerSaveBtn',
            title: 'Шаг 4/4: Сохранение',
            text: 'Сохраните итоговый набор тем. После этого переходите к календарю публикаций.',
            placement: 'left'
        }
    ],
    '/posting-plan': [
        {
            selector: '#planChannelSelect',
            title: 'Шаг 1/4: Канал и параметры',
            text: 'Выберите канал, частоту и час публикации.',
            placement: 'right'
        },
        {
            selector: '#planPreviewBtn',
            title: 'Шаг 2/4: Построение календаря',
            text: 'Система сформирует календарь на основе тем и частоты.',
            placement: 'right'
        },
        {
            selector: '#planItemsBody',
            title: 'Шаг 3/4: Ручная правка',
            text: 'Можно поправить дату, время и тему каждой публикации.',
            placement: 'top'
        },
        {
            selector: '#planSaveBtn',
            title: 'Шаг 4/4: Сохранение черновика',
            text: 'Сохраненный черновик снова откроется при следующем входе на страницу.',
            placement: 'left'
        }
    ],
    '/dashboard': [
        {
            selector: '#publishNowTopic',
            title: 'Шаг 1/4: Тема публикации',
            text: 'Можно указать общую тему вручную или оставить поле пустым.',
            placement: 'bottom'
        },
        {
            selector: '#publishNowChannelsGrid',
            title: 'Шаг 2/4: Выбор каналов',
            text: 'Отметьте один или несколько каналов для ручной публикации.',
            placement: 'top'
        },
        {
            selector: 'button[onclick*="publishNow"]',
            title: 'Шаг 3/4: Публикация',
            text: 'Запустите ручную публикацию. Текст адаптируется под платформу и канал.',
            placement: 'left'
        },
        {
            selector: '#recentPublications',
            title: 'Шаг 4/4: Результат',
            text: 'Здесь отображаются последние публикации и их статус.',
            placement: 'top'
        }
    ],
    '/agent': [
        {
            selector: '#agentControlPanel',
            title: 'Шаг 1/5: Контур агента',
            text: 'Здесь запускается semantic core, research и генерация нового draft.',
            placement: 'right'
        },
        {
            selector: '#agentRebuildBtn',
            title: 'Шаг 2/5: Semantic core',
            text: 'Пересоберите семантику и актуальные вопросы перед новой генерацией.',
            placement: 'right'
        },
        {
            selector: '#agentRunsPanel',
            title: 'Шаг 3/5: История run',
            text: 'Список показывает статусы quality gate и публикации по каждому запуску.',
            placement: 'left'
        },
        {
            selector: '#agentPreviewPanel',
            title: 'Шаг 4/5: Редактура',
            text: 'Откройте run, отредактируйте текст, пересчитайте quality и сохраните feedback.',
            placement: 'top'
        },
        {
            selector: '#agentPublishBtn',
            title: 'Шаг 5/5: Публикация',
            text: 'Публикуйте только approve run (или после ручного подтверждения).',
            placement: 'top'
        }
    ]
};

let guideState = null;

function escapeGuideHtml(value) {
    return (value || '')
        .toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizePathname(pathname) {
    const clean = (pathname || '/').split('?')[0].replace(/\/+$/, '');
    return clean || '/';
}

function isGuideDisabled() {
    return loadFromStorage(GUIDE_DISABLED_KEY, false) === true;
}

function setGuideDisabled(flag) {
    saveToStorage(GUIDE_DISABLED_KEY, !!flag);
    updateGuideLauncherUi();
}

function hasSeenGuide(pathname) {
    return loadFromStorage(`${GUIDE_SEEN_PREFIX}${pathname}`, false) === true;
}

function markGuideSeen(pathname) {
    saveToStorage(`${GUIDE_SEEN_PREFIX}${pathname}`, true);
}

function getGuideStepsForPath(pathname) {
    const allSteps = GUIDE_STEPS_BY_PATH[pathname] || [];
    return allSteps.filter((step) => !!document.querySelector(step.selector));
}

function clearGuideHighlightAndPopover() {
    if (!guideState) return;
    if (guideState.popover) {
        guideState.popover.dispose();
        guideState.popover = null;
    }
    if (guideState.anchor) {
        guideState.anchor.classList.remove('snoomi-guide-highlight');
        guideState.anchor = null;
    }
}

function finishGuide(markSeen = true) {
    if (!guideState) return;
    const path = guideState.pathname;
    clearGuideHighlightAndPopover();
    guideState = null;
    if (markSeen) {
        markGuideSeen(path);
    }
}

function renderCurrentGuideStep() {
    if (!guideState) return;

    const { steps, index } = guideState;
    if (index < 0 || index >= steps.length) {
        finishGuide(true);
        return;
    }

    clearGuideHighlightAndPopover();

    const step = steps[index];
    const anchor = document.querySelector(step.selector);
    if (!anchor) {
        guideState.index += 1;
        renderCurrentGuideStep();
        return;
    }

    guideState.anchor = anchor;
    anchor.classList.add('snoomi-guide-highlight');
    anchor.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });

    const nextLabel = index === steps.length - 1 ? 'Готово' : 'Дальше';
    const prevDisabled = index === 0 ? 'disabled' : '';
    const contentHtml = `
        <div class="small mb-2">${escapeGuideHtml(step.text)}</div>
        <div class="d-flex justify-content-end gap-2">
            <button type="button" class="btn btn-sm btn-outline-secondary" data-guide-action="prev" ${prevDisabled}>Назад</button>
            <button type="button" class="btn btn-sm btn-primary" data-guide-action="next">${nextLabel}</button>
        </div>
        <div class="d-flex justify-content-between mt-2">
            <button type="button" class="btn btn-link btn-sm p-0 text-muted" data-guide-action="skip">Пропустить</button>
            <button type="button" class="btn btn-link btn-sm p-0 text-danger" data-guide-action="disable">Отключить подсказки</button>
        </div>
    `;

    guideState.popover = new bootstrap.Popover(anchor, {
        trigger: 'manual',
        html: true,
        sanitize: false,
        container: 'body',
        placement: step.placement || 'auto',
        customClass: 'snoomi-guide-popover',
        title: `${escapeGuideHtml(step.title)} (${index + 1}/${steps.length})`,
        content: contentHtml
    });
    guideState.popover.show();
}

function startGuideTour(options = {}) {
    const force = !!options.force;
    const pathname = normalizePathname(window.location.pathname);
    const steps = getGuideStepsForPath(pathname);
    if (!steps.length) return;

    if (!force && (isGuideDisabled() || hasSeenGuide(pathname))) {
        return;
    }

    if (guideState) {
        finishGuide(false);
    }

    guideState = {
        pathname: pathname,
        steps: steps,
        index: 0,
        anchor: null,
        popover: null
    };
    renderCurrentGuideStep();
}

function handleGuideAction(action) {
    if (!guideState) return;

    if (action === 'next') {
        if (guideState.index >= guideState.steps.length - 1) {
            finishGuide(true);
            return;
        }
        guideState.index += 1;
        renderCurrentGuideStep();
        return;
    }

    if (action === 'prev') {
        guideState.index = Math.max(0, guideState.index - 1);
        renderCurrentGuideStep();
        return;
    }

    if (action === 'skip') {
        finishGuide(true);
        return;
    }

    if (action === 'disable') {
        setGuideDisabled(true);
        finishGuide(true);
    }
}

function buildGuideLauncher() {
    const pathname = normalizePathname(window.location.pathname);
    const steps = getGuideStepsForPath(pathname);
    if (!steps.length) return;
    if (document.getElementById('snoomiGuideLauncher')) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'dropup snoomi-guide-launcher';
    wrapper.id = 'snoomiGuideLauncher';
    wrapper.innerHTML = `
        <button class="btn btn-primary btn-sm dropdown-toggle" type="button" id="snoomiGuideMenuBtn" data-bs-toggle="dropdown" aria-expanded="false">
            <i class="fas fa-map-signs me-1"></i>Подсказки
        </button>
        <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="snoomiGuideMenuBtn">
            <li><button class="dropdown-item" type="button" id="snoomiGuideStartBtn"><i class="fas fa-play me-2"></i>Показать подсказки</button></li>
            <li><button class="dropdown-item" type="button" id="snoomiGuideDisableBtn"><i class="fas fa-ban me-2"></i>Отключить подсказки</button></li>
            <li><button class="dropdown-item d-none" type="button" id="snoomiGuideEnableBtn"><i class="fas fa-check me-2"></i>Включить подсказки</button></li>
        </ul>
    `;
    document.body.appendChild(wrapper);

    const startBtn = document.getElementById('snoomiGuideStartBtn');
    const disableBtn = document.getElementById('snoomiGuideDisableBtn');
    const enableBtn = document.getElementById('snoomiGuideEnableBtn');

    if (startBtn) {
        startBtn.addEventListener('click', () => {
            if (isGuideDisabled()) {
                showToast('info', 'Подсказки отключены', 'Включите подсказки в этом меню, чтобы запустить тур.');
                return;
            }
            startGuideTour({ force: true });
        });
    }
    if (disableBtn) {
        disableBtn.addEventListener('click', () => {
            setGuideDisabled(true);
            finishGuide(false);
            showToast('info', 'Подсказки отключены', 'Подсказки больше не будут показываться автоматически.');
        });
    }
    if (enableBtn) {
        enableBtn.addEventListener('click', () => {
            setGuideDisabled(false);
            showToast('success', 'Подсказки включены', 'Теперь можно снова запускать подсказки по шагам.');
        });
    }

    updateGuideLauncherUi();
}

function updateGuideLauncherUi() {
    const disableBtn = document.getElementById('snoomiGuideDisableBtn');
    const enableBtn = document.getElementById('snoomiGuideEnableBtn');
    if (!disableBtn || !enableBtn) return;

    if (isGuideDisabled()) {
        disableBtn.classList.add('d-none');
        enableBtn.classList.remove('d-none');
    } else {
        disableBtn.classList.remove('d-none');
        enableBtn.classList.add('d-none');
    }
}

function initGuideHints() {
    const pathname = normalizePathname(window.location.pathname);
    const steps = getGuideStepsForPath(pathname);
    if (!steps.length) return;

    buildGuideLauncher();
    if (!isGuideDisabled() && !hasSeenGuide(pathname)) {
        setTimeout(() => startGuideTour({ force: false }), 700);
    }
}

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Проверяем подключение
    window.addEventListener('online', () => {
        showToast('success', 'Соединение восстановлено', 'Интернет подключен');
    });
    
    window.addEventListener('offline', () => {
        showToast('warning', 'Нет соединения', 'Проверьте подключение к интернету');
    });
    
    // Добавляем CSRF токен ко всем AJAX запросам
    const csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (csrfToken && window.jQuery && typeof window.jQuery.ajaxSetup === 'function') {
        window.jQuery.ajaxSetup({
            headers: {
                'X-CSRF-TOKEN': csrfToken.getAttribute('content')
            }
        });
    }
    
    // Инициализация tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Инициализация popovers
    const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
    popoverTriggerList.map(function (popoverTriggerEl) {
        return new bootstrap.Popover(popoverTriggerEl);
    });
    
    // Плавная прокрутка для якорей
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    document.addEventListener('click', function (event) {
        const actionButton = event.target.closest('[data-guide-action]');
        if (!actionButton) return;
        event.preventDefault();
        handleGuideAction(actionButton.dataset.guideAction);
    });

    initGuideHints();
});