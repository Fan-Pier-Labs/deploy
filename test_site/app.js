// JavaScript for Deploy Test Site
// This file is loaded by index.html to test the deployment
(function() {
    'use strict';
    
    let counter = 0;
    const counterElement = document.getElementById('counter');
    const domainElement = document.getElementById('domain');
    const timestampElement = document.getElementById('timestamp');
    const versionElement = document.getElementById('version');
    
    // Update domain
    domainElement.textContent = window.location.hostname;
    
    // Set version (update this on each deployment to test cache invalidation)
    versionElement.textContent = 'v1.0.1';
    
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
    console.log('Deploy Test Site - JavaScript loaded successfully!');
    console.log('Domain:', window.location.hostname);
    console.log('Protocol:', window.location.protocol);
    console.log('Version:', versionElement.textContent);
    console.log('Cache invalidation test - if you see this version, cache was invalidated!');
})();
