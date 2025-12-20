const tg = window.Telegram?.WebApp;

if (!tg) {
    alert("Открой это приложение внутри Telegram");
} else {
    tg.expand?.();
    tg.setHeaderColor?.('#0a0e1a');
    tg.setBackgroundColor?.('#0a0e1a');
}

window.addEventListener("error", (e) => {
    console.error("JS ERROR:", e?.error || e?.message || e);
    alert("Ошибка в приложении: " + (e?.message || "см. console"));
});

let SYMBOLS = {"RUB": "₽", "USD": "$", "EUR": "€"};
let currentCurrency = "RUB";
let currentPeriod = 'month';
let currentType = 'expense';
let currentLanguage = 'ru';
let allTransactions = [];
let allCategories = new Set();
let quickButtons = [];

// Charts
let incomeExpenseChart = null;
let categoryChart = null;
let trendChart = null;

document.getElementById('sub-date').valueAsDate = new Date();
document.getElementById('date-picker').valueAsDate = new Date();

function tgInitData() {
    return tg?.initData || "";
}

async function tgFetch(url, options = {}) {
    const initData = tgInitData();
    if (!initData) {
        throw new Error("Нет Telegram initData. Открой WebApp внутри Telegram через кнопку бота.");
    }

    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json; charset=utf-8");
    }
    headers.set("X-Tg-Init-Data", initData);

    const res = await fetch(url, { ...options, headers });
    const text = await res.text();
    let parsed;
    try { parsed = JSON.parse(text); } catch { parsed = text; }

    if (!res.ok) {
        console.error("API error", res.status, parsed);
        throw new Error(parsed?.error || ("API error " + res.status));
    }
    return parsed;
}

// ========== НОВАЯ ФУНКЦИЯ: СЖАТИЕ ИЗОБРАЖЕНИЯ ==========
async function compressImage(file, maxWidth = 1920, quality = 0.85) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = (e) => {
            const img = new Image();
            
            img.onload = () => {
                // Вычисляем новые размеры (сохраняя пропорции)
                let width = img.width;
                let height = img.height;
                
                if (width > maxWidth) {
                    height = (height * maxWidth) / width;
                    width = maxWidth;
                }
                
                // Создаём canvas для сжатия
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);
                
                // Конвертируем в JPEG с указанным качеством
                canvas.toBlob(
                    (blob) => {
                        if (!blob) {
                            reject(new Error('Failed to compress image'));
                            return;
                        }
                        resolve(blob);
                    },
                    'image/jpeg',
                    quality
                );
            };
            
            img.onerror = () => reject(new Error('Failed to load image'));
            img.src = e.target.result;
        };
        
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsDataURL(file);
    });
}

// ========== ФУНКЦИЯ: РАБОТА С КАМЕРОЙ ==========
function openCamera() {
    tg?.HapticFeedback?.impactOccurred?.('light');
    
    const input = document.getElementById('receipt-input');
    input.click();
}

// Обработчик выбора фото
document.getElementById('receipt-input').addEventListener('change', async function(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Проверка типа
    if (!file.type.startsWith('image/')) {
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert('Выберите изображение (JPG, PNG, WEBP)');
        return;
    }

    tg?.HapticFeedback?.impactOccurred?.('medium');
    
    // Показываем индикатор загрузки
    const submitBtn = document.getElementById('submit-btn');
    const originalText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="loading"></span> Сжимаем фото...';
    submitBtn.disabled = true;

    try {
        // Сжимаем изображение
        const compressedBlob = await compressImage(file, 1920, 0.85);
        
        console.log(`Original size: ${(file.size / 1024 / 1024).toFixed(2)}MB`);
        console.log(`Compressed size: ${(compressedBlob.size / 1024 / 1024).toFixed(2)}MB`);
        
        // Проверяем размер после сжатия
        if (compressedBlob.size > 4 * 1024 * 1024) { // 4MB лимит
            tg?.HapticFeedback?.notificationOccurred?.('error');
            alert('Даже после сжатия файл слишком большой. Попробуй сфотографировать чек ближе.');
            return;
        }
        
        submitBtn.innerHTML = '<span class="loading"></span> Обрабатываем чек...';
        
        // Конвертируем в base64
        const base64 = await blobToBase64(compressedBlob);
        
        // Отправляем на сервер
        const result = await tgFetch('/api/process-receipt', {
            method: 'POST',
            body: JSON.stringify({
                image: base64,
                date: document.getElementById('date-picker').value
            })
        });

        tg?.HapticFeedback?.notificationOccurred?.('success');
        
        // Показываем результат
        const data = result?.data || result;
        if (data.items && data.items.length > 0) {
            const totalAmount = data.items.reduce((sum, item) => sum + item.amount, 0);
            alert(`✅ Распознано ${data.items.length} позиций на сумму ${totalAmount} ${SYMBOLS[currentCurrency]}\n\nТовары:\n` + 
                  data.items.map(item => `• ${item.name}: ${item.amount}`).join('\n'));
        }
        
        // Перезагружаем статистику
        await loadStats();
        
    } catch (e) {
        console.error('Receipt processing error:', e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert('Не удалось обработать чек: ' + (e?.message || e));
    } finally {
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
        event.target.value = ''; // Сбрасываем input
    }
});

// Вспомогательная функция для конвертации Blob в base64
function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            // Убираем префикс "data:image/jpeg;base64,"
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

// ========== iOS-STYLE SWIPE TO DELETE ==========
class SwipeHandler {
    constructor(container, itemElement, backgroundElement, onDelete) {
        this.container = container;
        this.element = itemElement;
        this.background = backgroundElement;
        this.onDelete = onDelete;
        this.startX = 0;
        this.currentX = 0;
        this.isDragging = false;
        this.isOpen = false;
        this.threshold = 80;
        this.maxSwipe = 90;

        this.element.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: true });
        this.element.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        this.element.addEventListener('touchend', this.handleTouchEnd.bind(this), { passive: true });
    }

    handleTouchStart(e) {
        this.startX = e.touches[0].clientX;
        this.currentX = this.startX;
        this.isDragging = true;
        this.element.classList.add('swiping');
    }

    handleTouchMove(e) {
        if (!this.isDragging) return;

        this.currentX = e.touches[0].clientX;
        const diff = this.startX - this.currentX;

        if (diff > 0) {
            e.preventDefault();
            const translateX = -Math.min(diff, this.maxSwipe);
            this.element.style.transform = `translateX(${translateX}px)`;
            
            if (Math.abs(translateX) > 10 && !this.background.classList.contains('visible')) {
                this.background.classList.add('visible');
                tg?.HapticFeedback?.impactOccurred?.('light');
            }
        }
    }

    handleTouchEnd(e) {
        if (!this.isDragging) return;

        this.isDragging = false;
        this.element.classList.remove('swiping');
        this.element.classList.add('snap-back');

        const diff = this.startX - this.currentX;

        if (diff > this.threshold) {
            this.open();
        } else {
            this.close();
        }

        setTimeout(() => {
            this.element.classList.remove('snap-back');
        }, 300);
    }

    open() {
        this.isOpen = true;
        this.element.style.transform = `translateX(-${this.maxSwipe}px)`;
        this.element.classList.add('swiped-open');
        this.background.classList.add('visible');
        tg?.HapticFeedback?.impactOccurred?.('medium');
    }

    close() {
        this.isOpen = false;
        this.element.style.transform = 'translateX(0)';
        this.element.classList.remove('swiped-open');
        this.background.classList.remove('visible');
    }

    reset() {
        this.close();
    }
}

const swipeHandlers = [];

function closeAllSwipes() {
    swipeHandlers.forEach(handler => handler.close());
}

let scrollTimeout;
window.addEventListener('scroll', () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
        closeAllSwipes();
    }, 100);
}, { passive: true });

// ========== RENDER HISTORY ITEMS ==========
function renderHistoryItems(items, container, limit = null) {
    const itemsToRender = limit ? items.slice(0, limit) : items;
    const sym = SYMBOLS[currentCurrency] || '';
    
    container.innerHTML = "";
    swipeHandlers.length = 0;

    if (itemsToRender.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <div class="empty-state-text">Здесь будет история твоих операций</div>
            </div>
        `;
        return;
    }

    itemsToRender.forEach(item => {
        const isIncome = item.type === 'income';
        const color = isIncome ? 'green' : 'red';
        const sign = isIncome ? '+' : '-';
        const dateObj = new Date(item.created_at);
        const dateStr = dateObj.toLocaleDateString('ru-RU', {day:'numeric', month:'short'});

        const containerDiv = document.createElement('div');
        containerDiv.className = 'swipe-container';

        containerDiv.innerHTML = `
            <div class="swipe-background">
                <div class="delete-btn" onclick="handleDeleteClick(${item.id})">🗑️</div>
            </div>
            <div class="history-item">
                <div class="history-info">
                    <div class="history-desc">${item.description}</div>
                    <div class="history-meta">
                        <span>${dateStr}</span>
                        <span>•</span>
                        <span>${item.category}</span>
                    </div>
                </div>
                <div class="history-amount ${color}">${sign}${item.amount} ${sym}</div>
            </div>
        `;

        const historyItem = containerDiv.querySelector('.history-item');
        const background = containerDiv.querySelector('.swipe-background');
        const handler = new SwipeHandler(containerDiv, historyItem, background, () => deleteItem(item.id));
        swipeHandlers.push(handler);

        container.appendChild(containerDiv);
    });
}

// ========== CHARTS ==========
function initializeCharts() {
    const chartConfig = {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
            legend: {
                labels: {
                    color: '#94a3b8',
                    font: {
                        family: 'Outfit',
                        size: 12
                    }
                }
            }
        },
        scales: {
            y: {
                ticks: { color: '#94a3b8' },
                grid: { color: 'rgba(255, 255, 255, 0.05)' }
            },
            x: {
                ticks: { color: '#94a3b8' },
                grid: { color: 'rgba(255, 255, 255, 0.05)' }
            }
        }
    };

    // Income/Expense Chart
    const ieCtx = document.getElementById('incomeExpenseChart');
    if (ieCtx) {
        incomeExpenseChart = new Chart(ieCtx, {
            type: 'bar',
            data: {
                labels: ['Доход', 'Расход'],
                datasets: [{
                    label: 'Сумма',
                    data: [0, 0],
                    backgroundColor: [
                        'rgba(16, 185, 129, 0.6)',
                        'rgba(248, 113, 113, 0.6)'
                    ],
                    borderColor: [
                        'rgb(16, 185, 129)',
                        'rgb(248, 113, 113)'
                    ],
                    borderWidth: 2,
                    borderRadius: 12
                }]
            },
            options: chartConfig
        });
    }

    // Category Chart
    const catCtx = document.getElementById('categoryChart');
    if (catCtx) {
        categoryChart = new Chart(catCtx, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: [{
                    data: [],
                    backgroundColor: [
                        '#3b82f6', '#10b981', '#8b5cf6', '#f59e0b',
                        '#ef4444', '#06b6d4', '#ec4899', '#14b8a6'
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                ...chartConfig,
                cutout: '70%'
            }
        });
    }

    // Trend Chart
    const trendCtx = document.getElementById('trendChart');
    if (trendCtx) {
        trendChart = new Chart(trendCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Доход',
                        data: [],
                        borderColor: 'rgb(16, 185, 129)',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Расход',
                        data: [],
                        borderColor: 'rgb(248, 113, 113)',
                        backgroundColor: 'rgba(248, 113, 113, 0.1)',
                        tension: 0.4,
                        fill: true
                    }
                ]
            },
            options: chartConfig
        });
    }
}

function updateCharts() {
    const dateFrom = document.getElementById('stats-date-from').value;
    const dateTo = document.getElementById('stats-date-to').value;
    const category = document.getElementById('stats-category').value;

    let filtered = [...allTransactions];

    if (dateFrom) {
        const fromDate = new Date(dateFrom);
        filtered = filtered.filter(item => new Date(item.created_at) >= fromDate);
    }

    if (dateTo) {
        const toDate = new Date(dateTo);
        toDate.setHours(23, 59, 59, 999);
        filtered = filtered.filter(item => new Date(item.created_at) <= toDate);
    }

    if (category) {
        filtered = filtered.filter(item => item.category === category);
    }

    // Calculate totals
    let totalIncome = 0;
    let totalExpense = 0;
    const categories = {};
    const dailyData = {};

    filtered.forEach(item => {
        const amount = parseFloat(item.amount) || 0;
        const date = new Date(item.created_at).toLocaleDateString('ru-RU');

        if (item.type === 'income') {
            totalIncome += amount;
            if (!dailyData[date]) dailyData[date] = { income: 0, expense: 0 };
            dailyData[date].income += amount;
        } else {
            totalExpense += amount;
            if (!dailyData[date]) dailyData[date] = { income: 0, expense: 0 };
            dailyData[date].expense += amount;
            
            const cat = item.category || 'Разное';
            categories[cat] = (categories[cat] || 0) + amount;
        }
    });

    // Update Income/Expense Chart
    if (incomeExpenseChart) {
        incomeExpenseChart.data.datasets[0].data = [totalIncome, totalExpense];
        incomeExpenseChart.update();
    }

    // Update Category Chart
    if (categoryChart) {
        const sortedCategories = Object.entries(categories).sort((a, b) => b[1] - a[1]);
        categoryChart.data.labels = sortedCategories.map(c => c[0]);
        categoryChart.data.datasets[0].data = sortedCategories.map(c => c[1]);
        categoryChart.update();
    }

    // Update Trend Chart
    if (trendChart) {
        const dates = Object.keys(dailyData).sort();
        trendChart.data.labels = dates;
        trendChart.data.datasets[0].data = dates.map(d => dailyData[d].income);
        trendChart.data.datasets[1].data = dates.map(d => dailyData[d].expense);
        trendChart.update();
    }
}

// ========== SCREEN NAVIGATION ==========
function switchTab(screenName, btn) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.getElementById(`screen-${screenName}`).classList.add('active');
    btn.classList.add('active');
    
    if (screenName === 'stats') {
        setTimeout(() => {
            if (!incomeExpenseChart) initializeCharts();
            updateCharts();
        }, 100);
    }
    
    closeAllSwipes();
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function openAllTransactions() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-all-transactions').classList.add('active');
    document.querySelector('.bottom-nav').style.display = 'none';
    
    document.getElementById('filter-date-from').value = '';
    document.getElementById('filter-date-to').value = '';
    document.getElementById('filter-category').value = '';
    
    applyTransactionFilters();
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function closeAllTransactions() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-wallet').classList.add('active');
    document.querySelector('.bottom-nav').style.display = 'block';
    closeAllSwipes();
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function openSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-settings').classList.add('active');
    document.querySelector('.bottom-nav').style.display = 'none';
    
    document.getElementById('current-currency').textContent = currentCurrency;
    document.getElementById('current-language').textContent = currentLanguage === 'ru' ? 'Русский' : 'English';
    
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function closeSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-wallet').classList.add('active');
    document.querySelector('.bottom-nav').style.display = 'block';
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function openCurrencySettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-currency').classList.add('active');
    document.getElementById('currency-select-setting').value = currentCurrency;
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function closeCurrencySettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-settings').classList.add('active');
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function openLanguageSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-language').classList.add('active');
    document.getElementById('language-select').value = currentLanguage;
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function closeLanguageSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-settings').classList.add('active');
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function openQuickButtonsSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-quick-buttons').classList.add('active');
    renderQuickButtons();
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

function closeQuickButtonsSettings() {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-settings').classList.add('active');
    tg?.HapticFeedback?.impactOccurred?.('soft');
}

// ========== QUICK BUTTONS ==========
function renderQuickButtons() {
    const container = document.getElementById('quick-buttons-list');
    container.innerHTML = '';

    quickButtons.forEach((button, index) => {
        const item = document.createElement('div');
        item.className = 'quick-button-item';
        item.innerHTML = `
            <div class="quick-button-input">
                <input type="text" class="input-field" placeholder="Например: Кофе 250" value="${button}" 
                       oninput="updateQuickButton(${index}, this.value)">
            </div>
            <button class="delete-quick-btn" onclick="removeQuickButton(${index})">×</button>
        `;
        container.appendChild(item);
    });

    document.getElementById('add-quick-btn').style.display = 
        quickButtons.length >= 6 ? 'none' : 'flex';
}

function addQuickButton() {
    if (quickButtons.length >= 6) {
        alert('Максимум 6 кнопок');
        return;
    }
    quickButtons.push('');
    renderQuickButtons();
    tg?.HapticFeedback?.impactOccurred?.('light');
}

function updateQuickButton(index, value) {
    quickButtons[index] = value;
}

function removeQuickButton(index) {
    quickButtons.splice(index, 1);
    renderQuickButtons();
    tg?.HapticFeedback?.impactOccurred?.('medium');
}

async function saveQuickButtons() {
    const validButtons = quickButtons.filter(b => b.trim());
    
    try {
        await tgFetch('/api/quick-buttons', {
            method: 'POST',
            body: JSON.stringify({ buttons: validButtons })
        });
        
        tg?.HapticFeedback?.notificationOccurred?.('success');
        alert('Кнопки сохранены! Перезапустите бота для обновления.');
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert('Ошибка сохранения: ' + (e?.message || e));
    }
}

async function loadQuickButtons() {
    try {
        const res = await tgFetch('/api/quick-buttons', { method: 'GET' });
        quickButtons = res?.data?.buttons || [];
    } catch (e) {
        console.error('Failed to load quick buttons:', e);
        quickButtons = [];
    }
}

// ========== SETTINGS ==========
async function saveCurrency() {
    const currency = document.getElementById('currency-select-setting').value;
    tg?.HapticFeedback?.selectionChanged?.();
    
    try {
        await tgFetch('/api/settings', {
            method: 'POST',
            body: JSON.stringify({ currency })
        });
        currentCurrency = currency;
        document.getElementById('current-currency').textContent = currency;
        loadStats();
    } catch (e) {
        console.error(e);
        alert('Ошибка сохранения валюты: ' + (e?.message || e));
    }
}

async function saveLanguage() {
    const language = document.getElementById('language-select').value;
    currentLanguage = language;
    document.getElementById('current-language').textContent = language === 'ru' ? 'Русский' : 'English';
    
    // TODO: Implement translations
    tg?.HapticFeedback?.notificationOccurred?.('success');
}

function applyTransactionFilters() {
    const dateFrom = document.getElementById('filter-date-from').value;
    const dateTo = document.getElementById('filter-date-to').value;
    const category = document.getElementById('filter-category').value;

    let filtered = [...allTransactions];

    if (dateFrom) {
        const fromDate = new Date(dateFrom);
        filtered = filtered.filter(item => new Date(item.created_at) >= fromDate);
    }

    if (dateTo) {
        const toDate = new Date(dateTo);
        toDate.setHours(23, 59, 59, 999);
        filtered = filtered.filter(item => new Date(item.created_at) <= toDate);
    }

    if (category) {
        filtered = filtered.filter(item => item.category === category);
    }

    document.getElementById('results-count').textContent = 
        `Найдено: ${filtered.length} ${filtered.length === 1 ? 'операция' : filtered.length < 5 ? 'операции' : 'операций'}`;

    const container = document.getElementById('history-all');
    renderHistoryItems(filtered, container);
}

function handleEnterKey(event) {
    if (event.key === 'Enter' || event.keyCode === 13) {
        event.preventDefault();
        sendData();
    }
}

function handleSubEnterKey(event, nextFieldId) {
    if (event.key === 'Enter' || event.keyCode === 13) {
        event.preventDefault();
        if (nextFieldId) {
            document.getElementById(nextFieldId).focus();
        } else {
            addSub();
        }
    }
}

function setType(type) {
    currentType = type;
    document.getElementById('btn-exp').className = `type-btn ${type === 'expense' ? 'active-exp' : ''}`;
    document.getElementById('btn-inc').className = `type-btn ${type === 'income' ? 'active-inc' : ''}`;
    const btn = document.getElementById('submit-btn');
    if (type === 'income') {
        btn.style.background = 'var(--gradient-green)';
        btn.style.boxShadow = '0 8px 24px rgba(16, 185, 129, 0.3)';
        btn.innerHTML = '💰 ЗАРАБОТАЛ';
    } else {
        btn.style.background = 'var(--gradient-red)';
        btn.style.boxShadow = '0 8px 24px rgba(248, 113, 113, 0.25)';
        btn.innerHTML = '💸 ПОТРАТИЛ';
    }
}

async function loadStats() {
    try {
        const res = await tgFetch(`/api/stats?period=${currentPeriod}`, { method: "GET" });
        const data = res?.data || res;

        currentCurrency = data.currency || "RUB";
        const sym = SYMBOLS[currentCurrency] || '';

        document.getElementById('total-balance').innerText = `${data.total_balance ?? 0} ${sym}`;
        document.getElementById('inc-val').innerText = `+${data.period?.income ?? 0}`;
        document.getElementById('exp-val').innerText = `-${data.period?.expense ?? 0}`;

        allTransactions = data.history || [];
        
        allCategories.clear();
        allTransactions.forEach(item => {
            if (item.category) allCategories.add(item.category);
        });

        const updateCategorySelects = () => {
            ['filter-category', 'stats-category'].forEach(id => {
                const select = document.getElementById(id);
                if (select) {
                    select.innerHTML = '<option value="">Все категории</option>';
                    Array.from(allCategories).sort().forEach(cat => {
                        const option = document.createElement('option');
                        option.value = cat;
                        option.textContent = cat;
                        select.appendChild(option);
                    });
                }
            });
        };

        updateCategorySelects();

        const previewContainer = document.getElementById('history-preview');
        renderHistoryItems(allTransactions, previewContainer, 5);

        const subList = document.getElementById('subs-list');
        subList.innerHTML = "";
        const subs = data.subscriptions || [];
        
        if (subs.length === 0) {
            subList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🔔</div>
                    <div class="empty-state-text">У тебя пока нет подписок</div>
                </div>
            `;
        } else {
            subs.forEach(sub => {
                const dateObj = new Date(sub.next_date);
                const dateStr = dateObj.toLocaleDateString('ru-RU');
                
                const item = document.createElement('div');
                item.className = 'sub-item';
                item.innerHTML = `
                    <div class="sub-info">
                        <h4>${sub.name}</h4>
                        <div class="sub-date">След. оплата: ${dateStr}</div>
                    </div>
                    <div class="sub-actions">
                        <div class="sub-amount">${sub.amount} ${sub.currency}</div>
                        <div class="sub-delete" onclick="delSub(${sub.id})">×</div>
                    </div>
                `;
                subList.appendChild(item);
            });
        }

    } catch (e) {
        console.error(e);
        alert("Не удалось загрузить данные: " + (e?.message || e));
    }
}

async function sendData() {
    const input = document.getElementById('expense');
    const dateInput = document.getElementById('date-picker');
    if(!input.value) {
        tg?.HapticFeedback?.notificationOccurred?.('error');
        return;
    }

    input.blur();
    dateInput.blur();

    tg?.HapticFeedback?.impactOccurred?.('medium');

    try {
        await tgFetch('/api/index', {
            method: 'POST',
            body: JSON.stringify({
                text: input.value,
                type: currentType,
                date: dateInput.value
            })
        });

        input.value = "";
        tg?.HapticFeedback?.notificationOccurred?.('success');
        await loadStats();
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert("Ошибка добавления: " + (e?.message || e));
    }
}

function setFilter(p, el) { 
    currentPeriod = p; 
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    el.classList.add('active'); 
    closeAllSwipes();
    tg?.HapticFeedback?.selectionChanged?.();
    loadStats(); 
}

async function addSub() {
    const name = document.getElementById('sub-name').value;
    const amount = document.getElementById('sub-amount').value;
    const date = document.getElementById('sub-date').value;
    const period = document.getElementById('sub-period').value;
    
    if(!name || !amount) {
        tg?.HapticFeedback?.notificationOccurred?.('error');
        return;
    }

    try {
        await tgFetch('/api/subs', {
            method: 'POST',
            body: JSON.stringify({
                action: 'add',
                name, amount, date, period,
                currency: currentCurrency
            })
        });

        document.getElementById('sub-name').value = "";
        document.getElementById('sub-amount').value = "";
        tg?.HapticFeedback?.notificationOccurred?.('success');
        loadStats();
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert("Ошибка подписки: " + (e?.message || e));
    }
}

async function delSub(id) {
    if(!confirm("Удалить подписку?")) return;
    
    tg?.HapticFeedback?.impactOccurred?.('heavy');
    
    try {
        await tgFetch('/api/subs', {
            method: 'POST',
            body: JSON.stringify({ action: 'delete', id })
        });
        tg?.HapticFeedback?.notificationOccurred?.('success');
        loadStats();
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert("Ошибка удаления подписки: " + (e?.message || e));
    }
}

function handleDeleteClick(id) {
    tg?.HapticFeedback?.impactOccurred?.('heavy');
    deleteItem(id);
}

async function deleteItem(id) {
    try {
        await tgFetch('/api/delete', {
            method: 'POST',
            body: JSON.stringify({ id })
        });
        tg?.HapticFeedback?.notificationOccurred?.('success');
        await loadStats();
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert("Ошибка удаления: " + (e?.message || e));
    }
}

async function downloadReport() {
    try {
        const initData = tgInitData();
        if (!initData) {
            alert("Открой приложение внутри Telegram");
            return;
        }

        tg?.HapticFeedback?.impactOccurred?.('medium');

        const res = await fetch('/api/export', {
            method: "GET",
            headers: { "X-Tg-Init-Data": initData }
        });

        if (!res.ok) {
            tg?.HapticFeedback?.notificationOccurred?.('error');
            alert("Не удалось скачать отчет");
            return;
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = url;
        a.download = "finance_report.csv";
        document.body.appendChild(a);
        a.click();
        a.remove();

        URL.revokeObjectURL(url);
        tg?.HapticFeedback?.notificationOccurred?.('success');
    } catch (e) {
        console.error(e);
        tg?.HapticFeedback?.notificationOccurred?.('error');
        alert("Ошибка отчета: " + (e?.message || e));
    }
}

// Initialize
loadStats();
loadQuickButtons();

// ============ AI АССИСТЕНТ ============

let aiChatHistory = [];
let aiChatLoaded = false;

async function loadAIChatHistory() {
  if (aiChatLoaded) return; // Загружаем только 1 раз
  
  try {
    const response = await fetch('/api/ai-chat?history=true', {
      headers: { 'X-Tg-Init-Data': window.Telegram.WebApp.initData }
    });
    
    const data = await response.json();
    
    if (data.success && data.data.history) {
      aiChatHistory = data.data.history;
      aiChatLoaded = true;
      renderAIChat();
    }
  } catch (error) {
    console.error('Load AI history error:', error);
  }
}

function renderAIChat() {
  const container = document.getElementById('aiChatMessages');
  
  if (aiChatHistory.length === 0) {
    // Показываем приветствие (уже есть в HTML)
    return;
  }
  
  // Очищаем и рендерим сообщения
  container.innerHTML = aiChatHistory.map(msg => {
    const escaped = escapeHtml(msg.content);
    return `<div class="ai-message ${msg.role}">${escaped}</div>`;
  }).join('');
  
  // Скролл вниз
  setTimeout(() => {
    container.scrollTop = container.scrollHeight;
  }, 100);
}

async function sendAIMessage() {
  const input = document.getElementById('aiMessageInput');
  const message = input.value.trim();
  
  if (!message) return;
  
  // Очищаем поле
  input.value = '';
  
  // Добавляем сообщение пользователя
  aiChatHistory.push({ role: 'user', content: message });
  renderAIChat();
  
  // Показываем индикатор
  showTypingIndicator();
  
  try {
    const response = await fetch('/api/ai-chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tg-Init-Data': window.Telegram.WebApp.initData
      },
      body: JSON.stringify({ message })
    });
    
    const data = await response.json();
    
    hideTypingIndicator();
    
    if (data.success && data.data.message) {
      aiChatHistory.push({
        role: 'assistant',
        content: data.data.message
      });
      renderAIChat();
    } else {
      showToast('Ошибка AI', 'error');
    }
    
  } catch (error) {
    hideTypingIndicator();
    console.error('AI error:', error);
    showToast('Не удалось связаться с AI', 'error');
  }
}

function askAI(question) {
  document.getElementById('aiMessageInput').value = question;
  sendAIMessage();
}

function showTypingIndicator() {
  const container = document.getElementById('aiChatMessages');
  const indicator = document.createElement('div');
  indicator.className = 'ai-message typing';
  indicator.id = 'typingIndicator';
  indicator.innerHTML = `
    <div class="typing-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  container.appendChild(indicator);
  container.scrollTop = container.scrollHeight;
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typingIndicator');
  if (indicator) indicator.remove();
}

async function clearAIChat() {
  if (!confirm('Очистить историю чата с AI?')) return;
  
  aiChatHistory = [];
  renderAIChat();
  showToast('История очищена', 'success');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML.replace(/\n/g, '<br>');
}

// Загрузка истории при открытии AI экрана
const originalShowScreen = window.showScreen;
window.showScreen = function(screenId) {
  originalShowScreen(screenId);
  
  if (screenId === 'aiScreen') {
    loadAIChatHistory();
  }
};

// ============ AI АССИСТЕНТ (ОБНОВЛЁННАЯ ВЕРСИЯ) ============

let aiChatHistory = [];
let aiChatLoaded = false;

async function loadAIChatHistory() {
  if (aiChatLoaded) return;
  
  try {
    const response = await fetch('/api/ai-assistant?history=true', {
      headers: { 'X-Tg-Init-Data': window.Telegram.WebApp.initData }
    });
    
    const data = await response.json();
    
    if (data.success && data.data.history) {
      aiChatHistory = data.data.history;
      aiChatLoaded = true;
      renderAIChat();
    }
  } catch (error) {
    console.error('Load AI history error:', error);
  }
}

function renderAIChat() {
  const container = document.getElementById('aiChatMessages');
  
  if (aiChatHistory.length === 0) {
    return; // Показываем приветствие из HTML
  }
  
  container.innerHTML = aiChatHistory.map(msg => {
    const escaped = escapeHtml(msg.content);
    return `<div class="ai-message ${msg.role}">${escaped}</div>`;
  }).join('');
  
  setTimeout(() => {
    container.scrollTop = container.scrollHeight;
  }, 100);
}

async function sendAIMessage() {
  const input = document.getElementById('aiMessageInput');
  const message = input.value.trim();
  
  if (!message) return;
  
  input.value = '';
  
  aiChatHistory.push({ role: 'user', content: message });
  renderAIChat();
  
  showTypingIndicator();
  
  try {
    const response = await fetch('/api/ai-assistant', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tg-Init-Data': window.Telegram.WebApp.initData
      },
      body: JSON.stringify({ 
        message,
        with_history: true  // Включаем историю
      })
    });
    
    const data = await response.json();
    
    hideTypingIndicator();
    
    if (data.success && data.data.message) {
      aiChatHistory.push({
        role: 'assistant',
        content: data.data.message
      });
      renderAIChat();
    } else {
      showToast('Ошибка AI', 'error');
    }
    
  } catch (error) {
    hideTypingIndicator();
    console.error('AI error:', error);
    showToast('Не удалось связаться с AI', 'error');
  }
}

function askAI(question) {
  document.getElementById('aiMessageInput').value = question;
  sendAIMessage();
}

function showTypingIndicator() {
  const container = document.getElementById('aiChatMessages');
  const indicator = document.createElement('div');
  indicator.className = 'ai-message typing';
  indicator.id = 'typingIndicator';
  indicator.innerHTML = `
    <div class="typing-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  container.appendChild(indicator);
  container.scrollTop = container.scrollHeight;
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typingIndicator');
  if (indicator) indicator.remove();
}

async function clearAIChat() {
  if (!confirm('Очистить историю чата с AI?')) return;
  
  aiChatHistory = [];
  renderAIChat();
  showToast('История очищена', 'success');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML.replace(/\n/g, '<br>');
}

// Загрузка истории при открытии AI экрана
const originalShowScreen = window.showScreen;
window.showScreen = function(screenId) {
  originalShowScreen(screenId);
  
  if (screenId === 'aiScreen') {
    loadAIChatHistory();
  }
};
