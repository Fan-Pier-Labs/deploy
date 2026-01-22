// Simple JavaScript to update the page dynamically
(function() {
    'use strict';
    
    let counter = 0;
    const counterElement = document.getElementById('counter');
    const domainElement = document.getElementById('domain');
    const timestampElement = document.getElementById('timestamp');
    
    // Update domain
    domainElement.textContent = window.location.hostname;
    
    // Update timestamp
    function updateTimestamp() {
        const now = new Date();
        timestampElement.textContent = now.toLocaleString();
    }
    updateTimestamp();
    
    // Update counter every second
    function updateCounter() {
        counter++;
        counterElement.textContent = counter;
        
        // Add a subtle animation
        counterElement.style.transform = 'scale(1.1)';
        setTimeout(() => {
            counterElement.style.transform = 'scale(1)';
        }, 200);
    }
    
    // Start the counter
    setInterval(updateCounter, 1000);
    
    // Update timestamp every minute
    setInterval(updateTimestamp, 60000);
    
    // Log to console for debugging
    console.log('S3 Deployment Test Site - JavaScript loaded successfully!');
    console.log('Domain:', window.location.hostname);
    console.log('Protocol:', window.location.protocol);
})();
