// InventoryScannerManager
// Isolated, Lazy-loaded, Non-blocking Barcode Scanner Module

const InventoryScannerManager = (function() {
    let _inputElement = null;
    let _isInitialized = false;
    let _debounceTimer = null;
    let _lastScanTime = 0;
    let _lastBarcode = null;
    
    // Config
    const DEBOUNCE_MS = 300;

    function _mountHiddenInput() {
        if (_inputElement) return;

        _inputElement = document.createElement('input');
        _inputElement.type = 'text';
        _inputElement.id = 'global-scanner-input';
        _inputElement.setAttribute('autocomplete', 'off');
        _inputElement.setAttribute('autofocus', 'true');
        
        // Hide the input completely
        _inputElement.style.position = 'absolute';
        _inputElement.style.opacity = '0';
        _inputElement.style.pointerEvents = 'none';
        _inputElement.style.left = '-9999px';
        _inputElement.style.top = '-9999px';

        document.body.appendChild(_inputElement);
    }

    function _attachListeners() {
        // Only attach once
        if (!_inputElement) return;

        _inputElement.addEventListener('input', (e) => {
            const barcode = e.target.value.trim();
            if (!barcode) return;

            // Debounce logic
            const now = Date.now();
            if (barcode === _lastBarcode && (now - _lastScanTime) < DEBOUNCE_MS) {
                e.target.value = ''; // Clear for next scan
                return;
            }

            _lastBarcode = barcode;
            _lastScanTime = now;

            if (_debounceTimer) clearTimeout(_debounceTimer);
            
            _debounceTimer = setTimeout(() => {
                _processScan(barcode);
                e.target.value = ''; // Clear after processing
            }, 50); // slight delay to allow full barcode to be pasted/typed by scanner
        });

        // Global click listener to refocus the scanner if we click outside of other inputs
        document.addEventListener('click', (e) => {
            // Do not refocus if user is actively interacting with another input/textarea
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                return;
            }
            // Delay focus slightly using requestAnimationFrame
            requestAnimationFrame(() => {
                _focusInput();
            });
        });
    }

    function _focusInput() {
        if (_inputElement) {
            _inputElement.focus();
        }
    }

    function _processScan(barcode) {
        if (typeof window.handleManualBarcode === 'function') {
            // Call the dashboard's handler
            window.handleManualBarcode(barcode);
        } else {
            console.warn("[Scanner] handleManualBarcode not defined on window");
        }
        
        // Refocus after scan
        requestAnimationFrame(() => {
            _focusInput();
        });
    }

    return {
        init: function() {
            if (_isInitialized) return;
            console.log("[Scanner] Initializing InventoryScannerManager...");
            
            _mountHiddenInput();
            _attachListeners();
            _focusInput();
            
            _isInitialized = true;
            console.log("[Scanner] InventoryScannerManager Initialized.");
        },
        
        focus: function() {
            requestAnimationFrame(() => {
                _focusInput();
            });
        }
    };
})();
