// Global variables for modal state
let modalState = {
    originalScrollPosition: 0,
    slideIndex: 1,
    modalOpen: false,
    bodyOverflowOriginal: ''
};

function openModal(clickedIndex) {
    modalState.originalScrollPosition = window.scrollY;
    modalState.slideIndex = clickedIndex || 1;
    modalState.modalOpen = true;
     
    const modal = document.getElementById("myModal");
    modal.style.display = "block";
    document.body.classList.add('modal-open');
    
    // Prevent background scrolling
    modalState.bodyOverflowOriginal = document.body.style.overflow;
    document.body.style.position = 'fixed';
    document.body.style.top = `-${modalState.originalScrollPosition}px`;
     
    showSlides(modalState.slideIndex);
    addEscapeKeyListener();
    
    // Add click outside listener
    modal.addEventListener('click', handleModalClick);
}

function handleModalClick(event) {
    if (event.target.id === "myModal") {
        closeModal();
    }
}

function cleanupModal() {
    const modal = document.getElementById("myModal");
    modal.removeEventListener('click', handleModalClick);
}

function closeModal() {
    cleanupModal();
    document.getElementById("myModal").style.display = "none";
    document.body.classList.remove('modal-open');
    
    // Restore body position and scrolling
    removeEscapeKeyListener();
    document.body.style.position = '';
    document.body.style.overflow = modalState.bodyOverflowOriginal;
    document.body.style.width = '';
    window.scrollTo(0, modalState.originalScrollPosition);
    
    modalState.modalOpen = false;
}

function addEscapeKeyListener() {
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && modalState.modalOpen) {
            closeModal();
        }
    });
}

function removeEscapeKeyListener() {
    document.removeEventListener('keydown', function(event) {
        if (event.key === 'Escape' && modalState.modalOpen) {
        }
    });
}

function plusSlides(n) {
    showSlides(modalState.slideIndex += n);
}

function showSlides(n) {
    var i;
    var slides = document.getElementsByClassName("mySlides");
    
    // Ensure slides exist
    if (!slides || slides.length === 0) {
        return;
    }
 
    if (n > slides.length) {
        modalState.slideIndex = 1; 
    }    
    if (n < 1) {
        modalState.slideIndex = slides.length;
    }
    
    // Hide all slides
    for (i = 0; i < slides.length; i++) {
        slides[i].style.display = "none";
    }

    // Safely display the current slide
    if (slides[modalState.slideIndex - 1]) {
        slides[modalState.slideIndex - 1].style.display = "flex";
    }
    
    // Add keyboard navigation
    document.onkeydown = function(e) {
        if (!modalState.modalOpen) return;
        
        if (e.key === "ArrowLeft") {
            plusSlides(-1);
        } else if (e.key === "ArrowRight") {
            plusSlides(1);
        }
    };
}


// DOMContentLoaded event listener for "Read More" functionality
document.addEventListener("DOMContentLoaded", function() {
    // Ensure modal is not displayed on page load
    const modal = document.getElementById("myModal");
    if (modal) {
        modal.style.display = "none";
        modalState.modalOpen = false;
    }
    
    // Read More functionality
    var readMoreLink = document.querySelector('.read-more-link');
    var summaryModal = document.getElementById('summaryModal');

    // Only if readMoreLink exists
    if (readMoreLink) {
        var summarySpan = document.querySelector('.summary-close');
        var fullSummary = document.querySelector('.summary-full');
        
        if (fullSummary) {
            fullSummary = fullSummary.textContent;

            readMoreLink.onclick = function() {
                summaryModal.style.display = "block";
                document.querySelector('.summary-modal-text').textContent = fullSummary;
                return false;
            }
        }

        summarySpan.onclick = function() {
            summaryModal.style.display = "none";
        }

        window.onclick = function(event) {
            if (event.target == summaryModal) {
                summaryModal.style.display = "none";
            }
        }
    }
});

// Extras Modal functionality - Custom Implementation
let extrasModalState = {
    modalOpen: false,
    originalScrollPosition: 0,
    bodyOverflowOriginal: ''
};

function openExtrasModal() {
    const modal = document.getElementById("extrasModal");
    if (!modal) return;

    extrasModalState.originalScrollPosition = window.scrollY;
    extrasModalState.modalOpen = true;
    
    modal.style.display = "flex";
    document.body.classList.add('modal-open');
    
    // Prevent background scrolling
    extrasModalState.bodyOverflowOriginal = document.body.style.overflow;
    document.body.style.position = 'fixed';
    document.body.style.overflow = 'hidden';
    document.body.style.width = '100%';
    document.body.style.top = `-${extrasModalState.originalScrollPosition}px`;
    
    // Add escape key listener
    addExtrasEscapeKeyListener();
    
    // Add click handler for backdrop
    modal.addEventListener('click', handleExtrasModalClick);
}

function closeExtrasModal() {
    const modal = document.getElementById("extrasModal");
    if (!modal) return;

    cleanupExtrasModal();
    modal.style.display = "none";
    document.body.classList.remove('modal-open');
    
    // Restore body position and scrolling
    removeExtrasEscapeKeyListener();
    document.body.style.position = '';
    document.body.style.overflow = extrasModalState.bodyOverflowOriginal;
    document.body.style.width = '';
    document.body.style.top = '';
    window.scrollTo(0, extrasModalState.originalScrollPosition);
    
    extrasModalState.modalOpen = false;
}

function handleExtrasModalClick(event) {
    if (event.target.id === "extrasModal") {
        closeExtrasModal();
    }
}

function cleanupExtrasModal() {
    const modal = document.getElementById("extrasModal");
    if (modal) {
        modal.removeEventListener('click', handleExtrasModalClick);
    }
}

function addExtrasEscapeKeyListener() {
    document.addEventListener('keydown', extrasEscapeKeyHandler);
}

function removeExtrasEscapeKeyListener() {
    document.removeEventListener('keydown', extrasEscapeKeyHandler);
}

function extrasEscapeKeyHandler(event) {
    if (event.key === 'Escape' && extrasModalState.modalOpen) {
        closeExtrasModal();
    }
}

function showExtrasTab(tabName) {
    // Remove active class from all tab buttons
    const tabButtons = document.querySelectorAll('.extras-tab-button');
    tabButtons.forEach(button => button.classList.remove('active'));
    
    // Hide all tab content
    const tabContents = document.querySelectorAll('.extras-tab-content');
    tabContents.forEach(content => content.classList.remove('active'));
    
    // Show selected tab content
    const selectedContent = document.getElementById(tabName + '-content');
    if (selectedContent) {
        selectedContent.classList.add('active');
    }
    
    // Activate the clicked tab button
    const clickedButton = event.target;
    if (clickedButton) {
        clickedButton.classList.add('active');
    }
}

// NFO Modal functionality
let nfoModalState = {
    modalOpen: false,
    originalScrollPosition: 0,
    bodyOverflowOriginal: ''
};

function openNfoModal() {
    const modal = document.getElementById("nfoModal");
    if (!modal) return;

    nfoModalState.originalScrollPosition = window.scrollY;
    nfoModalState.modalOpen = true;
    
    modal.style.display = "flex";
    document.body.classList.add('modal-open');
    
    // Prevent background scrolling
    nfoModalState.bodyOverflowOriginal = document.body.style.overflow;
    document.body.style.position = 'fixed';
    document.body.style.overflow = 'hidden';
    document.body.style.width = '100%';
    document.body.style.top = `-${nfoModalState.originalScrollPosition}px`;
    
    // Add escape key listener
    addNfoEscapeKeyListener();
    
    // Add click handler for backdrop
    modal.addEventListener('click', handleNfoModalClick);
}

function closeNfoModal() {
    const modal = document.getElementById("nfoModal");
    if (!modal) return;

    cleanupNfoModal();
    modal.style.display = "none";
    document.body.classList.remove('modal-open');
    
    // Restore body position and scrolling
    removeNfoEscapeKeyListener();
    document.body.style.position = '';
    document.body.style.overflow = nfoModalState.bodyOverflowOriginal;
    document.body.style.width = '';
    document.body.style.top = '';
    window.scrollTo(0, nfoModalState.originalScrollPosition);
    
    nfoModalState.modalOpen = false;
}

function handleNfoModalClick(event) {
    if (event.target.id === "nfoModal") {
        closeNfoModal();
    }
}

function cleanupNfoModal() {
    const modal = document.getElementById("nfoModal");
    if (modal) {
        modal.removeEventListener('click', handleNfoModalClick);
    }
}

function addNfoEscapeKeyListener() {
    document.addEventListener('keydown', nfoEscapeKeyHandler);
}

function removeNfoEscapeKeyListener() {
    document.removeEventListener('keydown', nfoEscapeKeyHandler);
}

function nfoEscapeKeyHandler(event) {
    if (event.key === 'Escape' && nfoModalState.modalOpen) {
        closeNfoModal();
    }
}

/* --- Game freshness (local vs Steam/GOG/Epic) --- */
document.addEventListener('DOMContentLoaded', function initFreshnessPanel() {
    const panel = document.getElementById('game-freshness-panel');
    const btn = document.getElementById('freshness-check-btn');
    const statusLine = document.getElementById('freshness-status-line');
    const details = document.getElementById('freshness-details');
    if (!panel || !btn || !statusLine) {
        return;
    }
    const gameUuid = panel.dataset.gameUuid;

    // local_version is parsed out of folder and file names on disk, and the
    // remote fields come from store APIs: escape before building markup.
    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderFreshness(data) {
        if (!data || data.error) {
            statusLine.innerHTML = `<span class="text-danger">${esc((data && data.error) || 'Check failed')}</span>`;
            if (details && data) {
                details.hidden = false;
                details.textContent = JSON.stringify(data, null, 2);
            }
            return;
        }
        const bits = [
            `<strong>${esc(data.status || 'unknown')}</strong>`,
            data.confidence ? `(${esc(data.confidence)})` : '',
            data.local_version ? `— local ${esc(data.local_version)}` : '',
            data.remote_version_summary ? `— ${esc(data.remote_version_summary)}` : '',
            data.checked_at ? `<span class="text-muted"> · checked ${esc(data.checked_at)}</span>` : '',
        ].filter(Boolean);
        statusLine.innerHTML = bits.join(' ');
        if (details) {
            details.hidden = false;
            details.textContent = JSON.stringify(
                {
                    reasons: data.reasons,
                    dlc: data.dlc,
                    local: data.local,
                    remotes: data.remotes,
                },
                null,
                2,
            );
        }
    }

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const prev = btn.textContent;
        btn.textContent = 'Checking…';
        statusLine.innerHTML = '<span class="text-muted">Contacting Steam / GOG / Epic…</span>';
        try {
            const headers = (typeof CSRFUtils !== 'undefined' && CSRFUtils.getHeaders)
                ? CSRFUtils.getHeaders({'Content-Type': 'application/json'})
                : { 'Content-Type': 'application/json' };
            const resp = await fetch(`/api/games/${gameUuid}/freshness/check`, {
                method: 'POST',
                headers,
                credentials: 'same-origin',
            });
            let data;
            try {
                data = await resp.json();
            } catch (parseErr) {
                data = { error: `Bad response (${resp.status})` };
            }
            if (!resp.ok && !data.error) {
                data.error = `Request failed (${resp.status})`;
            }
            renderFreshness(data);
        } catch (err) {
            statusLine.innerHTML = `<span class="text-danger">${esc(err.message || err)}</span>`;
        } finally {
            btn.disabled = false;
            btn.textContent = prev;
        }
    });
});
