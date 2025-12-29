/**
 * defAI Chat Interface Script
 * Handles UI interactions, API communication, and Markdown rendering.
 */

const CONFIG = {
    csrfToken: document.querySelector('meta[name="csrf-token"]')?.content,
    endpoints: {
        // API endpoints exposed by ai_assistant_bp (url_prefix="/api/ai")
        chat: '/api/ai/chat',
        history: '/api/ai/conversations',
        new: '/api/ai/conversations'
    },
    selectors: {
        messages: '#messages',
        chatStream: '#chatStream',
        form: '#chatForm',
        input: '#userInput',
        sidebar: '#sidebar',
        sidebarToggle: '#sidebarToggle',
        sidebarOverlay: '#sidebarOverlay',
        themeToggle: '#themeToggle',
        welcome: '#welcomeState',
        attachBtn: '#attachBtn',
        fileInput: '#fileInput',
        voiceBtn: '#voiceInputBtn',
        conversationList: '#conversationList',
        toastContainer: '#toast-container'
    }
};

const State = {
    isTyping: false,
    currentConversationId: null,
    theme: localStorage.getItem('theme') || 'light',
    recognition: null,
    isRecording: false
};

const UI = {
    elements: {},

    init() {
        // Initialize elements
        for (const [key, selector] of Object.entries(CONFIG.selectors)) {
            this.elements[key] = document.querySelector(selector);
        }

        this.setupTheme();
        this.setupMarkdown();
        this.setupEventListeners();
        this.setupSpeechRecognition();
        this.adjustTextareaHeight();

        // Check for existing conversation
        const appContainer = document.getElementById('app-container');
        if (appContainer && appContainer.dataset.conversationId) {
            State.currentConversationId = parseInt(appContainer.dataset.conversationId);
            this.loadConversationHistory(State.currentConversationId);
        }

        this.loadConversations();

        // Scroll listener for pagination
        if (this.elements.messages) {
            this.elements.messages.addEventListener('scroll', () => {
                if (this.elements.messages.scrollTop === 0) {
                    this.loadMoreMessages();
                }
            });
        }

        // Handle browser back/forward
        window.addEventListener('popstate', (event) => {
            if (event.state && event.state.conversationId) {
                this.setActiveConversation(event.state.conversationId, false);
            } else {
                // Handle initial state or root
                const pathParts = window.location.pathname.split('/');
                const linkOrId = pathParts[pathParts.length - 1];
                if (linkOrId && linkOrId !== 'chat') {
                    // Try to match linkOrId to a conversation? 
                    // For now, simpler to just reload or let default behavior if it was a deep link load.
                    // But if we are navigating back to "empty" chat, we might want to clear.
                    if (linkOrId === 'chat') {
                        this.clearActiveConversation();
                    }
                }
            }
        });
    },

    async loadConversations() {
        try {
            const response = await fetch(CONFIG.endpoints.history);
            if (!response.ok) throw new Error('Failed to load conversations');

            const conversations = await response.json();
            const listEl = this.elements.conversationList;

            if (!listEl) return;

            listEl.innerHTML = '';

            if (conversations.length === 0) {
                listEl.innerHTML = '<div class="text-center py-8 text-gray-400 text-sm italic">Aucune conversation récente</div>';
                return;
            }

            conversations.forEach(conv => {
                const el = document.createElement('a');
                // URL purement cosmétique: on pointe vers /defAI qui existe côté Flask
                const linkUrl = '/defAI';
                el.href = linkUrl;
                el.dataset.id = conv.id;
                el.dataset.link = conv.link || conv.id;

                // Style calc
                const isActive = State.currentConversationId === conv.id;
                const baseClass = "block p-3 rounded-xl transition-all duration-200 hover:bg-gray-100 dark:hover:bg-dark-surface group conversation-item";
                const activeClass = "bg-primary-50 dark:bg-primary-900/10 border border-primary-100 dark:border-primary-800";
                const inactiveClass = "border border-transparent";

                el.className = `${baseClass} ${isActive ? activeClass : inactiveClass}`;

                const time = new Date(conv.updated_at).toLocaleDateString();

                el.innerHTML = `
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 dark:text-primary-400 flex-shrink-0">
                            <i class="fas fa-comments text-xs"></i>
                        </div>
                        <div class="flex-1 min-w-0">
                            <h4 class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
                                ${conv.title || 'Nouvelle conversation'}
                            </h4>
                            <p class="text-xs text-gray-500 dark:text-gray-400 truncate">
                                ${conv.last_message || '...'}
                            </p>
                        </div>
                        <div class="text-[10px] text-gray-400 flex-shrink-0">
                            ${time}
                        </div>
                    </div>
                `;

                el.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.setActiveConversation(conv.id, true, conv.link || conv.id);
                    // Mobile sidebar handling
                    if (window.innerWidth < 1024) {
                        this.toggleSidebar();
                    }
                });

                listEl.appendChild(el);
            });

        } catch (error) {
            console.error('Error loading conversations:', error);
            this.showToast('Impossible de charger les conversations', 'error');
        }
    },

    setActiveConversation(id, pushState = true, linkPart = null) {
        if (State.currentConversationId === id) return;

        State.currentConversationId = id;

        // Update Sidebar UI
        document.querySelectorAll('.conversation-item').forEach(el => {
            const isActive = parseInt(el.dataset.id) === id;
            if (isActive) {
                el.classList.add('bg-primary-50', 'dark:bg-primary-900/10', 'border-primary-100', 'dark:border-primary-800');
                el.classList.remove('border-transparent');
            } else {
                el.classList.remove('bg-primary-50', 'dark:bg-primary-900/10', 'border-primary-100', 'dark:border-primary-800');
                el.classList.add('border-transparent');
            }
        });

        // Load Content
        this.loadConversationHistory(id);

        // Update URL (URL front uniquement, la page /defAI existe côté Flask)
        if (pushState) {
            const url = '/defAI';
            window.history.pushState({ conversationId: id }, '', url);
        }
    },

    clearActiveConversation() {
        State.currentConversationId = null;
        const chatStream = this.elements.chatStream;
        if (chatStream) {
            chatStream.innerHTML = '';
        }
        if (this.elements.welcome) this.elements.welcome.style.display = 'flex';
        // Reset sidebar selection
        document.querySelectorAll('.conversation-item').forEach(el => {
            el.classList.remove('bg-primary-50', 'dark:bg-primary-900/10', 'border-primary-100', 'dark:border-primary-800');
            el.classList.add('border-transparent');
        });
    },

    async loadConversationHistory(conversationId) {
        try {
            State.pagination = { page: 1, hasMore: true, isLoading: false }; // Reset pagination

            const response = await fetch(`/api/ai/conversations/${conversationId}?page=1`);
            if (!response.ok) throw new Error('Failed to load conversation');

            const data = await response.json();
            const messages = data.messages || [];

            // Update pagination state
            if (data.pagination) {
                State.pagination.page = data.pagination.page;
                State.pagination.hasMore = data.pagination.has_more;
            }

            // Clear existing and show
            const chatStream = this.elements.chatStream;
            if (chatStream) {
                chatStream.innerHTML = '';

                if (this.elements.welcome) {
                    this.elements.welcome.style.display = messages.length ? 'none' : 'flex';
                }

                messages.forEach(msg => {
                    const isUser = msg.sender_id === (data.user_id || 0) || msg.message_type === 'user';
                    chatStream.appendChild(this.createMessageElement(msg.content, isUser));
                });
            }

            this.scrollToBottom();
            hljs.highlightAll();
        } catch (error) {
            console.error('Error loading history:', error);
            this.showToast('Erreur lors du chargement de la conversation', 'error');
        }
    },

    async loadMoreMessages() {
        if (!State.currentConversationId || !State.pagination.hasMore || State.pagination.isLoading) return;

        State.pagination.isLoading = true;
        const nextPage = State.pagination.page + 1;
        const currentHeight = this.elements.messages.scrollHeight;

        try {
            const response = await fetch(`/api/ai/conversations/${State.currentConversationId}?page=${nextPage}`);
            if (!response.ok) throw new Error('Failed to load more messages');

            const data = await response.json();
            const messages = data.messages || [];

            if (data.pagination) {
                State.pagination.page = data.pagination.page;
                State.pagination.hasMore = data.pagination.has_more;
            } else {
                State.pagination.hasMore = false;
            }

            // Prepend messages
            messages.reverse().forEach(msg => { // Reverse because we want oldest at top of prepend list? No, API returns chronological.
                // Wait, API returns chronological.
                // If I have [M1, M2] on page 2 (older) and [M3, M4] on page 1 (newer).
                // I want to prepend M1 then M2. 
                // messages is [M1, M2].
                // Prepending M1 then M2 results in M2 M1 M3 M4.
                // Correct order is M1 M2 M3 M4.
                // So I should prepend in reverse order of the list? 
                // No, I should prepend the BLOCK [M1, M2].
                // appendChild adds to bottom.
                // insertBefore adds to top.
                // If I loop messages:
                // Prepend M1: [M1, M3, M4]
                // Prepend M2: [M2, M1, M3, M4] -> WRONG.
                // So I must loop messages in REVERSE to prepend properly, OR create a fragment.
            });

            // Using a fragment is cleaner
            const fragment = document.createDocumentFragment();
            messages.forEach(msg => {
                const isUser = msg.sender_id === (data.user_id || 0) || msg.message_type === 'user';
                fragment.appendChild(this.createMessageElement(msg.content, isUser));
            });
            const chatStream = this.elements.chatStream;
            if (chatStream) {
                chatStream.insertBefore(fragment, chatStream.firstChild);
            }

            hljs.highlightAll();

            // Maintain scroll position
            const newHeight = this.elements.messages.scrollHeight;
            this.elements.messages.scrollTop = newHeight - currentHeight;

        } catch (error) {
            console.error('Error loading more messages:', error);
            this.showToast('Impossible de charger plus de messages', 'error');
        } finally {
            State.pagination.isLoading = false;
        }
    },

    setupTheme() {
        if (State.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            document.documentElement.classList.add('dark');
            if (this.elements.themeToggle) this.elements.themeToggle.checked = true;
        } else {
            document.documentElement.classList.remove('dark');
            if (this.elements.themeToggle) this.elements.themeToggle.checked = false;
        }
    },

    toggleTheme() {
        State.theme = State.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('theme', State.theme);
        this.setupTheme();
    },

    setupMarkdown() {
        // Configuration de marked pour le rendu Markdown
        marked.setOptions({
            highlight: function (code, lang) {
                try {
                    if (lang && hljs.getLanguage(lang)) {
                        return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
                    }
                    return hljs.highlightAuto(code).value;
                } catch (e) {
                    console.warn('Erreur de coloration syntaxique:', e);
                    return code; // Retourne le code non coloré en cas d'erreur
                }
            },
            langPrefix: 'hljs language-',
            breaks: true,
            gfm: true,
            smartLists: true,
            smartypants: true,
            xhtml: true
        });

        // Configuration de DOMPurify pour la sécurité
        if (window.DOMPurify) {
            DOMPurify.setConfig({
                ALLOWED_TAGS: [
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'p', 'a', 'ul', 'ol',
                    'li', 'b', 'i', 'strong', 'em', 'strike', 'code', 'hr', 'br', 'div',
                    'table', 'thead', 'tbody', 'tr', 'th', 'td', 'pre', 'span', 'img'
                ],
                ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class', 'target', 'rel'],
                ALLOW_DATA_ATTR: false
            });
        }
    },

    setupSpeechRecognition() {
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            State.recognition = new SpeechRecognition();
            State.recognition.continuous = false;
            State.recognition.interimResults = false;
            State.recognition.lang = 'fr-FR';

            State.recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                const input = this.elements.input;
                input.value += (input.value ? ' ' : '') + transcript;
                this.adjustTextareaHeight();
                this.stopRecording();
            };

            State.recognition.onerror = (event) => {
                console.error('Speech recognition error:', event.error);
                this.stopRecording();
                showToast('Erreur lors de la reconnaissance vocale: ' + event.error);
            };

            State.recognition.onend = () => {
                this.stopRecording();
            };
        } else {
            console.warn('Votre navigateur ne supporte pas la reconnaissance vocale');
            this.showToast('Votre navigateur ne supporte pas la reconnaissance vocale', 'error');
            if (this.elements.voiceBtn) this.elements.voiceBtn.style.display = 'none';
        }
    },

    toggleRecording() {
        if (!State.recognition) return;

        if (State.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    },

    startRecording() {
        try {
            State.recognition.start();
            State.isRecording = true;
            if (this.elements.voiceBtn) {
                this.elements.voiceBtn.classList.add('text-red-500', 'animate-pulse');
            }
        } catch (e) {
            console.error(e);
            this.showToast('Erreur lors du démarrage de la reconnaissance vocale', 'error');
        }
    },

    stopRecording() {
        if (State.recognition) State.recognition.stop();
        State.isRecording = false;
        if (this.elements.voiceBtn) {
            this.elements.voiceBtn.classList.remove('text-red-500', 'animate-pulse');
        }
    },

    toggleSidebar() {
        const sidebar = this.elements.sidebar;
        const overlay = this.elements.sidebarOverlay;

        if (!sidebar || !overlay) return;

        const isClosed = sidebar.classList.contains('-translate-x-full');

        if (isClosed) {
            sidebar.classList.remove('-translate-x-full');
            overlay.classList.remove('opacity-0', 'pointer-events-none');
        } else {
            sidebar.classList.add('-translate-x-full');
            overlay.classList.add('opacity-0', 'pointer-events-none');
        }
    },

    createMessageElement(content, isUser) {
        // Container globable du message
        const div = document.createElement('div');
        div.className = `flex flex-col w-full animate-fade-in ${isUser ? 'items-end' : 'items-start'}`;

        // Header (Nom de l'émetteur)
        const header = document.createElement('div');
        header.className = "flex items-center gap-2 mb-2 px-1";

        if (isUser) {
            header.innerHTML = `
                <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">VOUS</span>
                <div class="w-6 h-6 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                    <i class="fas fa-user text-[10px] text-gray-500 dark:text-gray-400"></i>
                </div>
            `;
            div.className = 'flex flex-col w-full animate-fade-in items-end'; // Align user to right
        } else {
            header.innerHTML = `
                <div class="w-6 h-6 rounded-full bg-gradient-to-tr from-primary-500 to-purple-600 flex items-center justify-center shadow-lg shadow-primary-500/20">
                    <i class="fas fa-robot text-[10px] text-white"></i>
                </div>
                <span class="text-xs font-semibold text-primary-600 dark:text-primary-400">defAI</span>
            `;
            div.className = 'flex flex-col w-full animate-fade-in items-start'; // Align AI to left
        }

        div.appendChild(header);

        // Contenu du message
        const messageBox = document.createElement('div');
        // On retire le style "bulle" pour l'IA, on garde un léger fond pour l'utilisateur

        if (isUser) {
            messageBox.className = "px-4 py-3 bg-gray-100 dark:bg-dark-surface rounded-2xl rounded-tr-sm text-gray-800 dark:text-gray-100 max-w-[85%] text-sm";
            messageBox.textContent = content; // Texte brut pour l'utilisateur
        } else {
            // Style "Document" pour l'IA : pas de fond contraint, pleine largeur relative
            messageBox.className = "w-full pl-0 lg:pl-8 text-gray-800 dark:text-gray-100";

            try {
                // 1. Parsing Markdown -> HTML
                // marked.parse renvoie une string HTML
                const rawHtml = marked.parse(content);

                // 2. Sanitization HTML (Sécurité)
                // On nettoie le HTML généré, pas le Markdown source !
                const cleanHtml = DOMPurify.sanitize(rawHtml, {
                    ALLOWED_TAGS: [
                        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'p', 'a', 'ul', 'ol',
                        'li', 'b', 'i', 'strong', 'em', 'strike', 'code', 'hr', 'br', 'div',
                        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'pre', 'span', 'img', 'kbd'
                    ],
                    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class', 'target', 'rel', 'data-language'],
                    FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'object', 'embed', 'link'],
                    ALLOW_DATA_ATTR: false
                });

                // 3. Injection sécurisée
                messageBox.innerHTML = `
                    <div class="markdown-body prose dark:prose-invert max-w-none">
                        ${cleanHtml}
                    </div>
                `;

                // Highlight.js
                messageBox.querySelectorAll('pre code').forEach((block) => {
                    hljs.highlightElement(block);
                });

                // Bouton de copie
                // On l'ajoute flottant à droite du bloc
                const copyContainer = document.createElement('div');
                copyContainer.className = "flex justify-end mt-2 opacity-0 group-hover:opacity-100 transition-opacity";

                const copyBtn = document.createElement('button');
                copyBtn.className = "text-xs text-gray-400 hover:text-primary-500 flex items-center gap-1";
                copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier';
                copyBtn.onclick = () => {
                    this.copyToClipboard(content);
                    this.showToast('Copié !', 'success');
                };
                copyContainer.appendChild(copyBtn);
                // messageBox.appendChild(copyContainer); // Optionnel, peut être bruyant sur chaque message

            } catch (error) {
                console.error('Erreur rendu Markdown:', error);
                messageBox.textContent = content;
            }
        }

        div.appendChild(messageBox);
        return div;
    },

    createTypingIndicator() {
        const div = document.createElement('div');
        div.className = 'flex w-full mb-6 justify-start animate-fade-in';
        div.id = 'typingIndicator';
        div.innerHTML = `
            <div class="glass dark:bg-dark-surface p-4 rounded-2xl rounded-bl-sm border border-gray-200 dark:border-dark-border flex gap-1">
                <div class="typing-dot w-2 h-2 bg-primary-500 rounded-full"></div>
                <div class="typing-dot w-2 h-2 bg-primary-500 rounded-full"></div>
                <div class="typing-dot w-2 h-2 bg-primary-500 rounded-full"></div>
            </div>
        `;
        return div;
    },

    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    },

    showToast(message, type = 'info') {
        const container = this.elements.toastContainer;
        if (!container) return;

        const el = document.createElement('div');
        el.className = 'pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg transform transition-all duration-300 translate-x-full opacity-0';

        const colors = {
            success: 'bg-green-500 text-white',
            error: 'bg-red-500 text-white',
            warning: 'bg-yellow-500 text-white',
            info: 'bg-primary-500 text-white'
        };
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };

        const colorClass = colors[type] || colors.info;
        el.className += ' ' + colorClass;

        el.innerHTML = `
            <i class="fas ${icons[type] || icons.info} text-lg"></i>
            <span class="text-sm font-medium">${message}</span>
        `;

        container.appendChild(el);

        // Animate in
        requestAnimationFrame(() => {
            el.classList.remove('translate-x-full', 'opacity-0');
        });

        // Hide after 3s
        setTimeout(() => {
            el.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => el.remove(), 300);
        }, 3000);
    },

    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    },

    setupSpeechRecognition() {
        if ('webkitSpeechRecognition' in window) {
            State.recognition = new webkitSpeechRecognition();
            State.recognition.continuous = true;
            State.recognition.interimResults = true;
            State.recognition.lang = 'fr-FR';

            State.recognition.onstart = () => {
                State.isRecording = true;
                if (this.elements.voiceBtn) {
                    this.elements.voiceBtn.classList.remove('text-gray-400');
                    this.elements.voiceBtn.classList.add('text-red-500', 'animate-pulse');
                }
            };

            State.recognition.onend = () => {
                State.isRecording = false;
                if (this.elements.voiceBtn) {
                    this.elements.voiceBtn.classList.add('text-gray-400');
                    this.elements.voiceBtn.classList.remove('text-red-500', 'animate-pulse');
                }
            };

            State.recognition.onresult = (event) => {
                let interimTranscript = '';
                let finalTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                if (finalTranscript) {
                    this.elements.input.value += finalTranscript + ' ';
                    this.adjustTextareaHeight();
                }
            };

            State.recognition.onerror = (event) => {
                console.error('Speech recognition error', event.error);
                this.toggleRecording(); // Stop on error
                // Ignore no-speech errors as they are common
                if (event.error !== 'no-speech') {
                    this.showToast('Erreur reconnaissance vocale: ' + event.error, 'error');
                }
            };
        } else {
            console.warn('Web Speech API not supported');
            this.showToast('Votre navigateur ne supporte pas la reconnaissance vocale', 'error');
            if (this.elements.voiceBtn) this.elements.voiceBtn.style.display = 'none';
        }
    },

    toggleRecording() {
        if (!State.recognition) return;

        if (State.isRecording) {
            State.recognition.stop();
        } else {
            State.recognition.start();
        }
    },

    scrollToBottom() {
        const container = this.elements.messages;
        if (container) container.scrollTop = container.scrollHeight;
    },

    adjustTextareaHeight() {
        const textarea = this.elements.input;
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    },

    setupEventListeners() {
        if (this.elements.form) {
            this.elements.form.addEventListener('submit', (e) => this.handleSubmit(e));
        }

        if (this.elements.input) {
            this.elements.input.addEventListener('input', () => this.adjustTextareaHeight());
            this.elements.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (this.elements.form) this.elements.form.dispatchEvent(new Event('submit'));
                }
            });
        }

        if (this.elements.sidebarToggle) {
            this.elements.sidebarToggle.addEventListener('click', () => this.toggleSidebar());
        }

        if (this.elements.sidebarOverlay) {
            this.elements.sidebarOverlay.addEventListener('click', () => this.toggleSidebar());
        }

        if (this.elements.themeToggle) {
            this.elements.themeToggle.addEventListener('click', () => this.toggleTheme());
        }

        if (this.elements.voiceBtn) {
            this.elements.voiceBtn.addEventListener('click', () => this.toggleRecording());
        }

        // Handle attachment button & file input
        if (this.elements.attachBtn && this.elements.fileInput) {
            this.elements.attachBtn.addEventListener('click', () => this.elements.fileInput.click());

            this.elements.fileInput.addEventListener('change', async (e) => {
                const files = e.target.files;
                if (!files || files.length === 0) return;

                // Initialize pending attachments if not exists
                if (!State.pendingAttachments) State.pendingAttachments = [];

                // Visual feedback of upload start
                this.elements.attachBtn.classList.add('text-blue-500', 'animate-pulse');
                this.showToast('Upload en cours...', 'info');

                try {
                    for (let i = 0; i < files.length; i++) {
                        const file = files[i];
                        // Determine preset based on type, defaulting to 'documents_upload' for generic files
                        // But since chat accepts images too, we might need logic.
                        // cloudinary_uploader.js has specific presets: profiles_upload, documents_upload, html_upload, assets_upload.
                        // 'auto' resource type usually works well with a generic unsigned preset if enabled.
                        // Assuming 'documents_upload' works for general files or use 'auto' logic if backend expects it.
                        // Let's use 'documents_upload' which seemed to be the general one, or 'auto' if configured.
                        // Actually, 'documents_upload' was for resources.
                        // Let's check file type.
                        let preset = 'documents_upload';
                        let resourceType = 'auto';

                        // Proceed with upload
                        const result = await uploadToCloudinary(file, preset, resourceType);

                        State.pendingAttachments.push({
                            type: file.type.startsWith('image/') ? 'image' : 'file',
                            name: file.name,
                            url: result.secure_url,
                            size: result.bytes,
                            mime_type: file.type || result.format || 'application/octet-stream'
                        });
                    }

                    this.showToast(`${files.length} fichier(s) prêt(s) à l'envoi`, 'success');
                    this.elements.attachBtn.classList.remove('animate-pulse');
                    this.elements.attachBtn.classList.add('text-green-500'); // Indicate success

                } catch (error) {
                    console.error('Upload failed:', error);
                    this.showToast("Erreur lors de l'upload: " + error.message, 'error');
                    this.elements.attachBtn.classList.remove('text-blue-500', 'animate-pulse');
                }
            });
        }

        const newChatBtn = document.getElementById('newChat');
        if (newChatBtn) {
            newChatBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.clearActiveConversation();
                window.history.pushState({}, '', '/ai/chat');
                this.elements.welcome ? this.elements.welcome.style.display = 'flex' : null;
            });
        }
    },

    async handleSubmit(e) {
        e.preventDefault();
        if (State.isTyping) return;

        const input = this.elements.input;
        const message = input.value.trim();
        const attachments = State.pendingAttachments || [];

        if (!message && attachments.length === 0) return;

        // Hide welcome screen
        if (this.elements.welcome) {
            this.elements.welcome.style.display = 'none';
        }

        // Add User Message (Text)
        if (message) {
            const chatStream = this.elements.chatStream;
            if (chatStream) {
                chatStream.appendChild(this.createMessageElement(message, true));
            }
        }

        // Add User Message (Attachments Visual feedback - optional, or just let backend echo)
        // For better UX, we could show them. For now, we trust the backend echo/confirmation.

        this.scrollToBottom();

        // Clear Input
        input.value = '';
        this.adjustTextareaHeight();
        if (this.elements.attachBtn) {
            this.elements.attachBtn.classList.remove('text-green-500', 'text-blue-500');
            this.elements.attachBtn.classList.add('text-gray-400');
        }
        // Clear pending attachments
        State.pendingAttachments = [];
        if (this.elements.fileInput) this.elements.fileInput.value = '';

        State.isTyping = true;

        // Show Typing Indicator
        const typingObj = this.createTypingIndicator();
        const chatStream = this.elements.chatStream;
        if (chatStream) {
            chatStream.appendChild(typingObj);
        }
        this.scrollToBottom();

        try {
            // Construct payload
            const payload = {
                message: message,
                conversation_id: State.currentConversationId,
                attachments: attachments
            };

            const response = await fetch(CONFIG.endpoints.chat, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CONFIG.csrfToken
                },
                body: JSON.stringify(payload)
            });

            // Remove Typing Indicator
            typingObj.remove();

            if (!response.ok) {
                const errData = await response.json();
                this.showToast(errData.error || 'Network response was not ok', 'error');
                throw new Error(errData.error || 'Network response was not ok');
            }

            const data = await response.json();

            // Update conversation ID if returned
            if (data.conversation_id) {
                State.currentConversationId = data.conversation_id;
            }

            // Note: The API returns { success: true, response: "AI Message...", ... }
            const aiContent = data.response || data.message || "Je ne sais pas quoi répondre. veuillez réessayer";

            // Add AI Message
            const chatStream = this.elements.chatStream;
            if (chatStream) {
                chatStream.appendChild(this.createMessageElement(aiContent, false));
            }
            this.scrollToBottom();

            // Highlight Code Blocks
            hljs.highlightAll();

        } catch (error) {
            console.error('Error:', error);
            typingObj.remove();
            const chatStream = this.elements.chatStream;
            if (chatStream) {
                chatStream.appendChild(this.createMessageElement(`Désolé, une erreur est survenue: ${error.message}`, false));
            }
            this.scrollToBottom();
        } finally {
            State.isTyping = false;
        }
    }
};

// Global Helper for Welcome Buttons
window.setInput = (text) => {
    const input = document.querySelector('#userInput');
    if (input) {
        input.value = text;
        input.focus();
        UI.adjustTextareaHeight();
    }
};

// Initialize on load
document.addEventListener('DOMContentLoaded', () => UI.init());
