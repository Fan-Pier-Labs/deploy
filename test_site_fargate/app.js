// Deploy Test Site (Fargate) - loaded by index.html
(function() {
    'use strict';
    
    let counter = 0;
    const counterElement = document.getElementById('counter');
    const domainElement = document.getElementById('domain');
    const timestampElement = document.getElementById('timestamp');
    const versionElement = document.getElementById('version');
    
    if (domainElement) domainElement.textContent = window.location.hostname;
    if (versionElement) versionElement.textContent = 'v1.0.0';
    
    function updateTimestamp() {
        const now = new Date();
        if (timestampElement) timestampElement.textContent = now.toLocaleString();
    }
    updateTimestamp();
    
    function updateCounter() {
        counter++;
        if (counterElement) {
            counterElement.textContent = counter;
            counterElement.style.transform = 'scale(1.1)';
            setTimeout(function() { counterElement.style.transform = 'scale(1)'; }, 200);
        }
    }
    
    setInterval(updateCounter, 1000);
    setInterval(updateTimestamp, 60000);
})();
