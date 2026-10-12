// 时区功能
let timezoneBoxVisible = true;

function toggleTimezoneBox() {
    const box = document.getElementById('timezone-floating-box');
    timezoneBoxVisible = !timezoneBoxVisible;
    box.style.display = timezoneBoxVisible ? 'block' : 'none';
}

function updateWorldTime() {
    const now = new Date();
    // 巴黎时间 (UTC+1)
    const parisTime = new Date(now.getTime() + (1 * 60 * 60 * 1000));
    document.getElementById('paris-time').textContent = formatTime(parisTime);
    document.getElementById('madrid-time').textContent = formatTime(parisTime);
    
    // 悉尼时间 (UTC+11)
    const sydneyTime = new Date(now.getTime() + (11 * 60 * 60 * 1000));
    document.getElementById('sydney-time').textContent = formatTime(sydneyTime);
    
    // 东京时间 (UTC+9)
    const tokyoTime = new Date(now.getTime() + (9 * 60 * 60 * 1000));
    document.getElementById('tokyo-time').textContent = formatTime(tokyoTime);
    
    // 北京时间 (UTC+8)
    const beijingTime = new Date(now.getTime() + (8 * 60 * 60 * 1000));
    document.getElementById('beijing-time').textContent = formatTime(beijingTime);
    
    // 泰越印 (UTC+7)
    const thailTime = new Date(now.getTime() + (7 * 60 * 60 * 1000));
    document.getElementById('thail-time').textContent = formatTime(thailTime);

    // 印度加尔各答 (UTC+5:30)
    const indoTime = new Date(now.getTime() + (5.5 * 60 * 60 * 1000));
    document.getElementById('indo-time').textContent = formatTime(indoTime);
    
    // 纽约时间 (UTC-5/-4)
    const newYorkTime = new Date(now.getTime() + (-5 * 60 * 60 * 1000));
    document.getElementById('newyork-time').textContent = formatTime(newYorkTime);
    
    // 伦敦时间 (UTC+0/+1)
    document.getElementById('london-time').textContent = formatTime(now);    
    document.getElementById('lisbon-time').textContent = formatTime(now);
    
}

function formatTime(date) {
    const year = date.getUTCFullYear();
    const month = (date.getUTCMonth() + 1).toString().padStart(2, '0');
    const day = date.getUTCDate().toString().padStart(2, '0');
    const hours = date.getUTCHours().toString().padStart(2, '0');
    const minutes = date.getUTCMinutes().toString().padStart(2, '0');
    const seconds = date.getUTCSeconds().toString().padStart(2, '0');
    const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getUTCDay()];
    return `${month}-${day} ${hours}:${minutes}:${seconds} ${week}`;
}

// 初始化时区功能
function initTimezone() {
    // 立即更新一次时间
    updateWorldTime();
    // 每秒更新一次
    setInterval(updateWorldTime, 1000);
}

// 在页面加载完成后初始化时区功能
document.addEventListener('DOMContentLoaded', function() {
    // 等待loadData完成后初始化时区
    setTimeout(initTimezone, 100);
});