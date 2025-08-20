// GUVI Link Hub - Main JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Global variables
    let isSearchMode = true;
    let currentLinks = [];
    let searchTimeout;
    
    // DOM elements
    const searchInput = document.getElementById('searchInput');
    const searchResults = document.getElementById('searchResults');
    const chatInterface = document.getElementById('chatInterface');
    const chatMessages = document.getElementById('chatMessages');
    const chatInput = document.getElementById('chatInput');
    const linksGrid = document.getElementById('linksGrid');
    const addLinkModal = document.getElementById('addLinkModal');
    const importModal = document.getElementById('importModal');
    const commandPalette = document.getElementById('commandPalette');
    
    // Initialize app
    init();
    
    function init() {
        setupEventListeners();
        loadInitialData();
        setupKeyboardShortcuts();
        setupOfflineSupport();
    }
    
    function setupEventListeners() {
        // Search functionality
        searchInput.addEventListener('input', handleSearch);
        searchInput.addEventListener('focus', () => searchResults.classList.remove('hidden'));
        document.addEventListener('click', handleOutsideClick);
        
        // Mode switching
        document.getElementById('searchMode').addEventListener('click', switchToSearchMode);
        document.getElementById('chatMode').addEventListener('click', switchToChatMode);
        document.getElementById('aiChatToggle').addEventListener('click', switchToChatMode);
        
        // Chat functionality
        document.getElementById('sendChatBtn').addEventListener('click', sendChatMessage);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendChatMessage();
        });
        
        // Modal controls
        document.getElementById('addLinkBtn').addEventListener('click', openAddLinkModal);
        document.getElementById('cancelAddLink').addEventListener('click', closeAddLinkModal);
        document.getElementById('addLinkForm').addEventListener('submit', handleAddLink);
        
        // Import functionality
        document.getElementById('importBtn').addEventListener('click', openImportModal);
        document.getElementById('cancelImport').addEventListener('click', closeImportModal);
        document.getElementById('processImport').addEventListener('click', handleImport);
        
        // Stats
        document.getElementById('statsBtn').addEventListener('click', showStats);
        
        // Category filtering
        document.querySelectorAll('.category-filter').forEach(btn => {
            btn.addEventListener('click', handleCategoryFilter);
        });
        
        // Link interactions
        document.addEventListener('click', handleLinkClick);
    }
    
    // Search functionality
    function handleSearch(e) {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();
        
        if (!query) {
            searchResults.classList.add('hidden');
            return;
        }
        
        searchTimeout = setTimeout(() => {
            if (isSearchMode) {
                performSearch(query);
            }
        }, 300);
    }
    
    async function performSearch(query) {
        try {
            const response = await fetch(`/search?q=${encodeURIComponent(query)}`);
            const links = await response.json();
            displaySearchResults(links);
        } catch (error) {
            console.error('Search error:', error);
            showNotification('Search failed. Please try again.', 'error');
        }
    }
    
    function displaySearchResults(links) {
        if (links.length === 0) {
            searchResults.innerHTML = '<div class="p-4 text-gray-500">No links found</div>';
        } else {
            searchResults.innerHTML = links.map(link => `
                <div class="p-4 hover:bg-gray-50 border-b last:border-b-0 cursor-pointer" onclick="openLink('${link.url}', ${link.id})">
                    <h4 class="font-medium text-gray-900">${link.title}</h4>
                    <p class="text-sm text-gray-600 mt-1">${link.description || ''}</p>
                    <div class="flex items-center justify-between mt-2">
                        <span class="text-xs px-2 py-1 bg-blue-100 text-blue-800 rounded-full">${link.category}</span>
                        <span class="text-xs text-gray-500">${link.clicks || 0} clicks</span>
                    </div>
                </div>
            `).join('');
        }
        searchResults.classList.remove('hidden');
    }
    
    // Mode switching
    function switchToSearchMode() {
        isSearchMode = true;
        document.getElementById('searchMode').classList.add('bg-white', 'text-guvi-dark', 'shadow-sm');
        document.getElementById('searchMode').classList.remove('text-gray-600');
        document.getElementById('chatMode').classList.remove('bg-white', 'text-guvi-dark', 'shadow-sm');
        document.getElementById('chatMode').classList.add('text-gray-600');
        
        chatInterface.classList.add('hidden');
        searchInput.placeholder = "Search links, ask AI anything... (Ctrl+K for quick search)";
    }
    
    function switchToChatMode() {
        isSearchMode = false;
        document.getElementById('chatMode').classList.add('bg-white', 'text-guvi-dark', 'shadow-sm');
        document.getElementById('chatMode').classList.remove('text-gray-600');
        document.getElementById('searchMode').classList.remove('bg-white', 'text-guvi-dark', 'shadow-sm');
        document.getElementById('searchMode').classList.add('text-gray-600');
        
        chatInterface.classList.remove('hidden');
        searchResults.classList.add('hidden');
        searchInput.placeholder = "Ask AI about links... (e.g., 'Show me machine learning resources')";
    }
    
    // Chat functionality
    async function sendChatMessage() {
        const message = chatInput.value.trim();
        if (!message) return;
        
        // Add user message
        addChatMessage(message, 'user');
        chatInput.value = '';
        
        // Add thinking indicator
        const thinkingId = addChatMessage('🤔 Thinking...', 'ai', true);
        
        try {
            const response = await fetch('/ai_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
            
            const data = await response.json();
            
            // Remove thinking indicator
            document.getElementById(thinkingId).remove();
            
            // Add AI response
            addChatMessage(data.response, 'ai');
            
            // Show relevant links if any
            if (data.relevant_links && data.relevant_links.length > 0) {
                addChatLinks(data.relevant_links);
            }
            
        } catch (error) {
            document.getElementById(thinkingId).remove();
            addChatMessage('Sorry, I encountered an error. Please try again.', 'ai');
            console.error('Chat error:', error);
        }
    }
    
    function addChatMessage(message, sender, isTemporary = false) {
        const messageId = 'msg-' + Date.now();
        const isUser = sender === 'user';
        const messageHtml = `
            <div id="${messageId}" class="flex items-start space-x-2 chat-message ${isUser ? 'justify-end' : ''}">
                ${!isUser ? `
                    <div class="w-8 h-8 bg-guvi-orange rounded-full flex items-center justify-center">
                        <i class="fas fa-robot text-white text-sm"></i>
                    </div>
                ` : ''}
                <div class="max-w-xs lg:max-w-md px-3 py-2 rounded-lg ${
                    isUser ? 'bg-guvi-orange text-white' : 'bg-gray-100 text-gray-800'
                }">
                    <p class="text-sm">${message}</p>
                </div>
                ${isUser ? `
                    <div class="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center">
                        <i class="fas fa-user text-gray-600 text-sm"></i>
                    </div>
                ` : ''}
            </div>
        `;
        
        chatMessages.insertAdjacentHTML('beforeend', messageHtml);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        return messageId;
    }
    
    function addChatLinks(links) {
        const linksHtml = `
            <div class="flex items-start space-x-2 chat-message">
                <div class="w-8 h-8 bg-guvi-orange rounded-full flex items-center justify-center">
                    <i class="fas fa-link text-white text-sm"></i>
                </div>
                <div class="max-w-md">
                    <div class="text-sm font-medium text-gray-700 mb-2">Here are some relevant links:</div>
                    <div class="space-y-2">
                        ${links.map(link => `
                            <div class="bg-white border rounded-lg p-3 hover:shadow-md transition-shadow cursor-pointer" onclick="openLink('${link.url}', ${link.id})">
                                <h4 class="font-medium text-sm text-gray-900">${link.title}</h4>
                                <p class="text-xs text-gray-600 mt-1">${link.description || ''}</p>
                                <div class="flex items-center justify-between mt-2">
                                    <span class="text-xs px-2 py-1 bg-blue-100 text-blue-800 rounded-full">${link.category}</span>
                                    <i class="fas fa-external-link-alt text-guvi-orange text-xs"></i>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
        
        chatMessages.insertAdjacentHTML('beforeend', linksHtml);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    
    // Link management
    async function handleAddLink(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        
        try {
            const response = await fetch('/add_link', {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (result.success) {
                showNotification('Link added successfully!', 'success');
                closeAddLinkModal();
                location.reload(); // Simple refresh for now
            } else {
                showNotification(result.error || 'Failed to add link', 'error');
            }
        } catch (error) {
            console.error('Add link error:', error);
            showNotification('Failed to add link. Please try again.', 'error');
        }
    }
    
    async function handleImport() {
        const content = document.getElementById('importText').value.trim();
        const category = document.getElementById('importCategory').value;
        const addedBy = document.getElementById('importAddedBy').value || 'Anonymous';
        
        if (!content) {
            showNotification('Please paste some content to import', 'error');
            return;
        }
        
        try {
            const response = await fetch('/import_from_text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content, category, added_by: addedBy })
            });
            
            const result = await response.json();
            
            if (result.success) {
                showNotification(`Successfully imported ${result.imported_count} links!`, 'success');
                closeImportModal();
                location.reload();
            } else {
                showNotification(result.error || 'Import failed', 'error');
            }
        } catch (error) {
            console.error('Import error:', error);
            showNotification('Import failed. Please try again.', 'error');
        }
    }
    
    // Category filtering
    function handleCategoryFilter(e) {
        const category = e.target.dataset.category;
        
        // Update active state
        document.querySelectorAll('.category-filter').forEach(btn => {
            btn.classList.remove('active', 'bg-guvi-orange', 'text-white');
            btn.classList.add('bg-gray-200', 'text-gray-700');
        });
        
        e.target.classList.add('active', 'bg-guvi-orange', 'text-white');
        e.target.classList.remove('bg-gray-200', 'text-gray-700');
        
        // Filter links
        const linkCards = document.querySelectorAll('.link-card');
        linkCards.forEach(card => {
            if (category === 'all' || card.dataset.category === category) {
                card.style.display = 'block';
            } else {
                card.style.display = 'none';
            }
        });
    }
    
    // Link interactions
    function handleLinkClick(e) {
        if (e.target.classList.contains('click-link')) {
            const linkId = e.target.dataset.id;
            trackLinkClick(linkId);
        } else if (e.target.classList.contains('delete-link') || e.target.closest('.delete-link')) {
            const linkId = e.target.dataset.id || e.target.closest('.delete-link').dataset.id;
            if (confirm('Are you sure you want to delete this link?')) {
                deleteLink(linkId);
            }
        }
    }
    
    async function trackLinkClick(linkId) {
        try {
            await fetch(`/click_link/${linkId}`);
        } catch (error) {
            console.error('Click tracking error:', error);
        }
    }
    
    async function deleteLink(linkId) {
        try {
            const response = await fetch(`/delete_link/${linkId}`);
            if (response.ok) {
                showNotification('Link deleted successfully', 'success');
                location.reload();
            }
        } catch (error) {
            console.error('Delete error:', error);
            showNotification('Failed to delete link', 'error');
        }
    }
    
    function openLink(url, linkId) {
        window.open(url, '_blank');
        if (linkId) {
            trackLinkClick(linkId);
        }
    }
    
    // Keyboard shortcuts
    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl+K for command palette
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                toggleCommandPalette();
            }
            
            // Escape to close modals/palette
            if (e.key === 'Escape') {
                closeAllModals();
            }
        });
    }
    
    function toggleCommandPalette() {
        const palette = document.getElementById('commandPalette');
        const input = document.getElementById('commandInput');
        
        if (palette.classList.contains('hidden')) {
            palette.classList.remove('hidden');
            input.focus();
            input.addEventListener('input', handleCommandInput);
        } else {
            palette.classList.add('hidden');
        }
    }
    
    function handleCommandInput(e) {
        const query = e.target.value.toLowerCase();
        const results = document.getElementById('commandResults');
        
        if (query.startsWith('/')) {
            // Command mode
            const commands = [
                { cmd: '/add', desc: 'Add new link', action: openAddLinkModal },
                { cmd: '/import', desc: 'Import links from Google Docs', action: openImportModal },
                { cmd: '/stats', desc: 'Show team statistics', action: showStats },
                { cmd: '/chat', desc: 'Switch to AI chat mode', action: switchToChatMode }
            ];
            
            const matchedCommands = commands.filter(c => c.cmd.includes(query));
            results.innerHTML = matchedCommands.map(c => `
                <div class="p-3 hover:bg-gray-50 cursor-pointer border-b" onclick="executeCommand('${c.cmd}')">
                    <div class="font-medium">${c.cmd}</div>
                    <div class="text-sm text-gray-600">${c.desc}</div>
                </div>
            `).join('') || '<div class="p-4 text-gray-500">No commands found</div>';
        } else if (query) {
            // Search mode
            performQuickSearch(query);
        } else {
            results.innerHTML = '<div class="p-4 text-gray-500 text-center">Start typing to search or try commands like \'/add\', \'/stats\', \'/import\'</div>';
        }
    }
    
    async function performQuickSearch(query) {
        try {
            const response = await fetch(`/search?q=${encodeURIComponent(query)}`);
            const links = await response.json();
            const results = document.getElementById('commandResults');
            
            if (links.length === 0) {
                results.innerHTML = '<div class="p-4 text-gray-500">No links found</div>';
            } else {
                results.innerHTML = links.slice(0, 5).map(link => `
                    <div class="p-3 hover:bg-gray-50 cursor-pointer border-b" onclick="openLink('${link.url}', ${link.id}); closeAllModals();">
                        <div class="font-medium">${link.title}</div>
                        <div class="text-sm text-gray-600">${link.description || ''}</div>
                        <div class="text-xs text-gray-500 mt-1">${link.category} • ${link.clicks || 0} clicks</div>
                    </div>
                `).join('');
            }
        } catch (error) {
            console.error('Quick search error:', error);
        }
    }
    
    // Statistics
    async function showStats() {
        try {
            const response = await fetch('/stats');
            const stats = await response.json();
            
            // Update stats in the UI
            document.getElementById('totalLinks').textContent = stats.total_links;
            document.getElementById('weeklyLinks').textContent = stats.links_this_week;
            
            // Show notification with more stats
            showNotification(`📊 Total: ${stats.total_links} links | This week: ${stats.links_this_week} | Categories: ${stats.categories}`, 'success', 5000);
        } catch (error) {
            console.error('Stats error:', error);
            showNotification('Failed to load statistics', 'error');
        }
    }
    
    // Modal controls
    function openAddLinkModal() {
        addLinkModal.classList.remove('hidden');
    }
    
    function closeAddLinkModal() {
        addLinkModal.classList.add('hidden');
        document.getElementById('addLinkForm').reset();
    }
    
    function openImportModal() {
        importModal.classList.remove('hidden');
    }
    
    function closeImportModal() {
        importModal.classList.add('hidden');
        document.getElementById('importText').value = '';
    }
    
    function closeAllModals() {
        addLinkModal.classList.add('hidden');
        importModal.classList.add('hidden');
        commandPalette.classList.add('hidden');
        searchResults.classList.add('hidden');
    }
    
    function handleOutsideClick(e) {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.classList.add('hidden');
        }
    }
    
    // Notifications
    function showNotification(message, type = 'info', duration = 3000) {
        const notification = document.createElement('div');
        notification.className = `notification p-4 rounded-lg shadow-lg text-white max-w-sm ${
            type === 'success' ? 'bg-green-500' : 
            type === 'error' ? 'bg-red-500' : 
            'bg-blue-500'
        }`;
        notification.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="flex-1">${message}</span>
                <button onclick="this.parentElement.parentElement.remove()" class="ml-2 text-white hover:text-gray-200">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
        
        document.getElementById('notifications').appendChild(notification);
        
        setTimeout(() => {
            if (notification.parentElement) {
                notification.classList.add('removing');
                setTimeout(() => notification.remove(), 300);
            }
        }, duration);
    }
    
    // Offline support
    function setupOfflineSupport() {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/static/sw.js')
                .then(registration => console.log('SW registered'))
                .catch(error => console.log('SW registration failed'));
        }
        
        // Handle online/offline events
        window.addEventListener('online', () => {
            showNotification('Back online! 🌐', 'success');
        });
        
        window.addEventListener('offline', () => {
            showNotification('You\'re offline. Cached links still available! 📱', 'info');
        });
    }
    
    // Command execution
    window.executeCommand = function(cmd) {
        const commands = {
            '/add': openAddLinkModal,
            '/import': openImportModal,
            '/stats': showStats,
            '/chat': switchToChatMode
        };
        
        if (commands[cmd]) {
            commands[cmd]();
            closeAllModals();
        }
    };
    
    // Load initial data
    function loadInitialData() {
        // Initial stats update
        showStats();
    }
    
    // Global functions for onclick handlers
    window.openLink = openLink;
    window.executeCommand = executeCommand;
});