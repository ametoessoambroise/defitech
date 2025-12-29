// Configuration
const CONFIG = {
    BACKEND_URL: window.location.origin,
    DEFAULT_IMAGES_PER_PAGE: 30,
    CLOUDINARY: {
        CLOUD_NAME: 'doqjyyf8w',
        UPLOAD_PRESET: 'ml_default',
        UPLOAD_URL: 'https://api.cloudinary.com/v1_1/doqjyyf8w/image/upload',
        SIMULATION_MODE: true
    }
};

// Éléments DOM
const elements = {
    searchInput: document.getElementById('searchImageInput'),
    searchButton: document.getElementById('searchImageButton'),
    searchType: document.getElementById('searchType'),
    colorFilter: document.getElementById('colorFilter'),
    suggestions: document.querySelectorAll('.suggestion-tag'),
    imageContainer: document.getElementById('imageContainer'),
    loadMoreBtn: document.getElementById('loadMoreBtn'),
    loadMoreSpinner: document.getElementById('loadMoreSpinner'),
    searchLoader: document.getElementById('searchLoader'),
    aiPrompt: document.getElementById('aiPrompt'),
    aiStyle: document.getElementById('aiStyle'),
    generateImageBtn: document.getElementById('generateImageBtn'),
    generatedImages: document.getElementById('generatedImages'),
    generateLoader: document.getElementById('generateLoader'),
    modal: document.getElementById('imageModal'),
    modalImage: document.getElementById('modalImage'),
    modalTitle: document.getElementById('modalTitle'),
    modalDescription: document.getElementById('modalDescription'),
    closeModal: document.getElementById('closeModal'),
    downloadBtn: document.getElementById('downloadBtn'),
    shareBtn: document.getElementById('shareBtn'),
    generateSimilarBtn: document.getElementById('generateSimilarBtn'),
    dropZone: document.getElementById('dropZone'),
    browseBtn: document.getElementById('browseBtn'),
    fileInput: document.getElementById('fileInput'),
    analyzeBtn: document.getElementById('analyzeBtn'),
    previewImage: document.getElementById('previewImage'),
    previewContainer: document.getElementById('previewContainer'),
    analysisResults: document.getElementById('analysisResults'),
    analysisTags: document.getElementById('analysisTags')
};

// État
const state = {
    currentPage: 1,
    currentSearchQuery: '',
    currentImage: null,
    fileToAnalyze: null
};

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupImageAnalysis();
    setupTabNavigation();
    setupDarkMode();
    fetchPopularImages();
});

// Dark Mode
function setupDarkMode() {
    const darkBtn = document.getElementById('dark');
    const isDark = localStorage.getItem('darkMode') === 'true';

    if (isDark) {
        document.documentElement.classList.add('dark');
    }

    darkBtn?.addEventListener('click', () => {
        document.documentElement.classList.toggle('dark');
        localStorage.setItem('darkMode', document.documentElement.classList.contains('dark'));
    });
}

// Navigation onglets
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-btn[data-tab]');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabName = button.getAttribute('data-tab');

            tabButtons.forEach(btn => {
                if (btn.hasAttribute('data-tab')) {
                    btn.classList.remove('bg-primary-600', 'text-white', 'shadow-lg', 'shadow-primary-600/30');
                    btn.classList.add('bg-white', 'dark:bg-gray-800', 'text-gray-700', 'dark:text-gray-300', 'border-2', 'border-gray-200', 'dark:border-gray-700');
                }
            });

            button.classList.remove('bg-white', 'dark:bg-gray-800', 'text-gray-700', 'dark:text-gray-300', 'border-2', 'border-gray-200', 'dark:border-gray-700');
            button.classList.add('bg-primary-600', 'text-white', 'shadow-lg', 'shadow-primary-600/30');

            tabContents.forEach(content => content.classList.add('hidden'));
            const activeContent = document.getElementById(`${tabName}-tab`);
            if (activeContent) {
                activeContent.classList.remove('hidden');
            }
        });
    });
}

// Event Listeners
function setupEventListeners() {
    elements.searchButton?.addEventListener('click', handleSearch);
    elements.searchInput?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSearch();
    });

    elements.suggestions.forEach(suggestion => {
        suggestion.addEventListener('click', () => {
            elements.searchInput.value = suggestion.textContent;
            handleSearch();
        });
    });

    elements.searchType?.addEventListener('change', handleSearch);
    elements.colorFilter?.addEventListener('change', handleSearch);
    elements.loadMoreBtn?.addEventListener('click', loadMoreImages);
    elements.generateImageBtn?.addEventListener('click', handleGenerateImage);
    elements.closeModal?.addEventListener('click', closeModal);
    elements.downloadBtn?.addEventListener('click', downloadImage);
    elements.shareBtn?.addEventListener('click', shareImage);
    elements.generateSimilarBtn?.addEventListener('click', generateSimilarImage);

    elements.modal?.addEventListener('click', (e) => {
        if (e.target === elements.modal) closeModal();
    });
}

// Analyse d'image
function setupImageAnalysis() {
    if (!elements.browseBtn || !elements.fileInput || !elements.dropZone || !elements.analyzeBtn) return;

    elements.browseBtn.addEventListener('click', (e) => {
        e.preventDefault();
        elements.fileInput.click();
    });

    elements.fileInput.addEventListener('change', handleFileSelect);

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        elements.dropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
        });
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        elements.dropZone.addEventListener(eventName, () => {
            elements.dropZone.classList.add('border-primary-500', 'bg-primary-50/50', 'dark:bg-primary-900/10');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        elements.dropZone.addEventListener(eventName, () => {
            elements.dropZone.classList.remove('border-primary-500', 'bg-primary-50/50', 'dark:bg-primary-900/10');
        });
    });

    elements.dropZone.addEventListener('drop', handleDrop);
    elements.analyzeBtn.addEventListener('click', analyzeImage);
}

function handleFileSelect(e) {
    const files = e.target.files;
    if (files && files.length > 0) {
        processImage(files[0]);
    }
    elements.fileInput.value = '';
}

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files && files.length > 0) {
        processImage(files[0]);
    }
}

function processImage(file) {
    if (!file) {
        showToast('Aucun fichier sélectionné', 'error');
        return;
    }

    if (!file.type.match('image.*')) {
        showToast('Veuillez sélectionner une image valide (JPG, PNG, etc.)', 'error');
        return;
    }

    const maxSize = 5 * 1024 * 1024;
    if (file.size > maxSize) {
        showToast('L\'image ne doit pas dépasser 5 Mo', 'error');
        return;
    }

    const reader = new FileReader();
    reader.onload = async function (e) {
        elements.previewImage.src = e.target.result;
        elements.previewContainer.classList.remove('hidden');
        elements.analyzeBtn.disabled = true; // Disable until upload complete
        elements.analyzeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Mise en ligne...</span>';

        try {
            // Upload to Cloudinary
            const result = await uploadToCloudinary(file, 'documents_upload', 'auto'); // Use appropriate preset
            state.fileToAnalyze = result.secure_url; // Store URL instead of file object
            showToast('Image chargée avec succès', 'success');

            elements.analyzeBtn.innerHTML = '<i class="fas fa-search"></i> <span>Analyser l\'image</span>';
            elements.analyzeBtn.disabled = false;
        } catch (error) {
            console.error(error);
            showToast('Erreur upload Cloudinary: ' + error.message, 'error');
            state.fileToAnalyze = null;
            elements.analyzeBtn.innerHTML = '<i class="fas fa-search"></i> <span>Analyser l\'image</span>';
            elements.analyzeBtn.disabled = false; // Allow retry or cancel
            return;
        }

        elements.analysisResults.classList.add('hidden');

        setTimeout(() => {
            elements.previewContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 100);
    };

    reader.onerror = () => showToast('Erreur lors de la lecture du fichier', 'error');
    reader.readAsDataURL(file);
}

async function analyzeImage() {
    if (!state.fileToAnalyze) {
        showToast('Veuillez sélectionner une image à analyser', 'error');
        return;
    }

    try {
        elements.analyzeBtn.disabled = true;
        elements.analyzeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Analyse en cours...</span>';

        const analysisResult = await simulateImageAnalysis(state.fileToAnalyze);
        displayAnalysisResults(analysisResult);

    } catch (error) {
        console.error('Erreur d\'analyse:', error);
        showToast(`Erreur: ${error.message}`, 'error');
    } finally {
        elements.analyzeBtn.disabled = false;
        elements.analyzeBtn.innerHTML = '<i class="fas fa-search"></i> <span>Analyser l\'image</span>';
    }
}

async function simulateImageAnalysis(imageUrl) {
    // imageUrl is now a robust Cloudinary URL or local data URL
    await new Promise(resolve => setTimeout(resolve, 1500));

    const categories = {
        nature: ['forêt', 'montagne', 'rivière', 'océan', 'plage', 'cascade', 'lac', 'désert', 'champ', 'fleur', 'arbre', 'ciel'],
        urbain: ['ville', 'bâtiment', 'rue', 'pont', 'architecture', 'gratte-ciel', 'métro', 'parc', 'fontaine', 'monument'],
        personnes: ['portrait', 'sourire', 'groupe', 'enfant', 'famille', 'couple', 'ami', 'voyage', 'aventure', 'sport'],
        animaux: ['chat', 'chien', 'oiseau', 'paysage', 'sauvage', 'nature', 'mignon', 'compagnon', 'faune'],
        nourriture: ['repas', 'restaurant', 'dessert', 'boisson', 'fruit', 'légume', 'cuisine', 'recette', 'gourmandise']
    };

    const categoryKeys = Object.keys(categories);
    const randomCategory = categoryKeys[Math.floor(Math.random() * categoryKeys.length)];
    const baseTags = [...categories[randomCategory]];
    const selectedTags = [];
    const numTags = 3 + Math.floor(Math.random() * 4);

    while (selectedTags.length < numTags && baseTags.length > 0) {
        const randomIndex = Math.floor(Math.random() * baseTags.length);
        selectedTags.push(baseTags.splice(randomIndex, 1)[0]);
    }

    return {
        tags: selectedTags,
        metadata: {
            width: 800 + Math.floor(Math.random() * 2000),
            height: 600 + Math.floor(Math.random() * 1500),
            format: ['JPEG', 'PNG', 'WEBP'][Math.floor(Math.random() * 3)],
            category: randomCategory,
            confidence: (70 + Math.floor(Math.random() * 30)) + '%'
        }
    };
}

function displayAnalysisResults(analysis) {
    elements.analysisResults.classList.remove('hidden');
    elements.analysisTags.innerHTML = '';

    analysis.tags.forEach(tag => {
        const tagElement = document.createElement('span');
        tagElement.className = 'px-4 py-2 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 rounded-full text-sm font-medium border border-primary-200 dark:border-primary-800 hover:-translate-y-0.5 transition-transform duration-200 cursor-default inline-block';
        tagElement.innerHTML = `<i class="fas fa-tag text-xs mr-1"></i>${tag}`;
        elements.analysisTags.appendChild(tagElement);
    });

    setTimeout(() => {
        elements.analysisResults.scrollIntoView({ behavior: 'smooth' });
    }, 100);
}

// Recherche
async function fetchPopularImages() {
    try {
        showLoader('searchLoader');
        const response = await fetch(`${CONFIG.BACKEND_URL}/api/search/images?query=popular&per_page=${CONFIG.DEFAULT_IMAGES_PER_PAGE}`);

        if (!response.ok) throw new Error('Erreur lors du chargement des images');

        const data = await response.json();

        displayImages(data.results || []);

    } catch (error) {
        console.error('Erreur:', error);
        showToast('Erreur lors du chargement. Mode démo activé.', 'warning');
        displayDummyImages();
    } finally {
        hideLoader('searchLoader');
    }
}

async function handleSearch() {
    const query = elements.searchInput.value.trim();
    if (!query) {
        showToast('Veuillez entrer un terme de recherche', 'warning');
        return;
    }

    elements.searchButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Recherche...</span>';
    elements.searchButton.disabled = true;

    state.currentSearchQuery = query;
    state.currentPage = 1;

    try {
        showLoader('searchLoader');
        elements.imageContainer.innerHTML = '';

        const color = elements.colorFilter.value;

        // Utiliser la nouvelle route backend
        let url = `${CONFIG.BACKEND_URL}/image-search/api/search/images?query=${encodeURIComponent(query)}&per_page=${CONFIG.DEFAULT_IMAGES_PER_PAGE}&page=${state.currentPage}`;

        if (color) {
            url += `&color=${color}`;
        }

        const response = await fetch(url);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || 'Erreur lors de la recherche');
        }

        const data = await response.json();
        displayImages(data.results || []);

        elements.loadMoreBtn.classList.toggle('hidden', !data.results || data.results.length < CONFIG.DEFAULT_IMAGES_PER_PAGE);

    } catch (error) {
        console.error('Erreur de recherche:', error);
        showToast(error.message || 'Erreur lors de la recherche. Mode démo activé.', 'warning');
        displayDummyImages();
    } finally {
        hideLoader('searchLoader');
        elements.searchButton.innerHTML = '<i class="fas fa-search"></i> <span>Rechercher</span>';
        elements.searchButton.disabled = false;
    }
}

async function loadMoreImages() {
    if (!state.currentSearchQuery) return;

    elements.loadMoreSpinner.classList.remove('hidden');
    state.currentPage++;

    try {
        showLoader('searchLoader');

        const color = elements.colorFilter.value;

        // Utiliser la nouvelle route backend
        let url = `${CONFIG.BACKEND_URL}/image-search/api/search/images?query=${encodeURIComponent(state.currentSearchQuery)}&per_page=${CONFIG.DEFAULT_IMAGES_PER_PAGE}&page=${state.currentPage}`;

        if (color) {
            url += `&color=${color}`;
        }

        const response = await fetch(url);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || 'Erreur lors du chargement des images');
        }

        const data = await response.json();
        elements.loadMoreSpinner.classList.add('hidden');
        displayImages(data.results || [], true);

        if (!data.results || data.results.length < CONFIG.DEFAULT_IMAGES_PER_PAGE) {
            elements.loadMoreBtn.classList.add('hidden');
        }

    } catch (error) {
        console.error('Erreur lors du chargement des images:', error);
        showToast(error.message || 'Erreur lors du chargement des images', 'error');
        elements.loadMoreSpinner.classList.add('hidden');
    } finally {
        hideLoader('searchLoader');
    }
}

function displayImages(images, append = false) {
    if (!images || images.length === 0) {
        if (!append) {
            elements.imageContainer.innerHTML = '<div class="col-span-full text-center py-16"><i class="fas fa-search text-6xl text-gray-300 dark:text-gray-600 mb-4"></i><p class="text-lg text-gray-500 dark:text-gray-400">Aucun résultat trouvé. Essayez une autre recherche.</p></div>';
        }
        return;
    }

    if (!append) {
        elements.imageContainer.innerHTML = '';
    }

    images.forEach(image => {
        const imageCard = createImageCard(image);
        elements.imageContainer.appendChild(imageCard);
    });
}

function createImageCard(imageData) {
    const imageCard = document.createElement('div');
    imageCard.className = 'image-card-hover bg-white dark:bg-gray-800 rounded-xl overflow-hidden shadow-lg cursor-pointer group';

    const imageWrapper = document.createElement('div');
    imageWrapper.className = 'relative overflow-hidden h-64';

    const img = document.createElement('img');
    img.src = imageData.small_url || imageData.thumb_url;

    img.alt = imageData.description || 'Sans titre';
    img.loading = 'lazy';
    img.className = 'w-full h-full object-cover transition-transform duration-500 group-hover:scale-110 opacity-0';

    img.onload = () => {
        img.classList.remove('opacity-0');
        img.classList.add('opacity-100');
    };

    const overlay = document.createElement('div');
    overlay.className = 'absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300';

    const imageInfo = document.createElement('div');
    imageInfo.className = 'p-4';

    const title = document.createElement('h3');
    title.className = 'text-base font-semibold text-gray-900 dark:text-white truncate mb-2';
    title.textContent = imageData.description || 'Sans titre';

    const meta = document.createElement('div');
    meta.className = 'flex justify-between items-center text-sm text-gray-600 dark:text-gray-400';

    const author = document.createElement('span');
    author.className = 'truncate flex items-center gap-1';
    author.innerHTML = `<i class="fas fa-user text-xs"></i>${imageData.user?.name || 'Seeker AI'}`;

    const likes = document.createElement('span');
    likes.className = 'flex items-center gap-1';
    likes.innerHTML = `<i class="fas fa-heart text-red-500"></i> ${imageData.likes || Math.floor(Math.random() * 100)}`;

    meta.appendChild(author);
    meta.appendChild(likes);
    imageInfo.appendChild(title);
    imageInfo.appendChild(meta);

    imageWrapper.appendChild(img);
    imageWrapper.appendChild(overlay);
    imageCard.appendChild(imageWrapper);
    imageCard.appendChild(imageInfo);

    imageCard.addEventListener('click', () => openImageModal({
        url: imageData.full_url || imageData.urls?.regular || imageData.urls?.full,
        title: imageData.description || 'Sans titre',
        description: imageData.description || '',
        downloadUrl: imageData.full_url || imageData.urls?.full,
        author: imageData.user?.name || 'Seeker AI'
    }));

    return imageCard;
}

function displayDummyImages() {
    const dummyImages = [];
    for (let i = 0; i < 12; i++) {
        dummyImages.push({
            id: `dummy-${i}`,
            url: `https://picsum.photos/400/300?random=${i}`,
            description: `Image ${i + 1}`,
            likes: Math.floor(Math.random() * 100),
            user: { name: 'Seeker AI' }
        });
    }
    displayImages(dummyImages);
}

// Génération
async function handleGenerateImage() {
    const prompt = elements.aiPrompt.value.trim();

    if (!prompt) {
        showToast('Veuillez décrire l\'image que vous souhaitez générer', 'warning');
        return;
    }

    try {
        elements.generateImageBtn.disabled = true;
        elements.generateImageBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>Génération...</span>';
        showLoader('generateLoader');

        const style = elements.aiStyle.value;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        const response = await fetch(`${CONFIG.BACKEND_URL}/api/generate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ prompt, style })
        });

        if (!response.ok) throw new Error('Erreur lors de la génération');

        const blob = await response.blob();
        const imageUrl = URL.createObjectURL(blob);
        displayGeneratedImage(imageUrl, prompt);

    } catch (error) {
        console.error('Erreur de génération:', error);
        showToast('Génération non disponible. Image de démonstration.', 'info');
        const demoImageUrl = `https://picsum.photos/600/400?random=${Date.now()}`;
        displayGeneratedImage(demoImageUrl, prompt);

    } finally {
        hideLoader('generateLoader');
        elements.generateImageBtn.disabled = false;
        elements.generateImageBtn.innerHTML = '<i class="fas fa-magic"></i> <span>Générer</span>';
    }
}

function displayGeneratedImage(imageUrl, prompt) {
    elements.generatedImages.innerHTML = `
        <div class="col-span-full bg-white dark:bg-gray-800 rounded-2xl overflow-hidden shadow-xl animate-fade-in">
            <img src="${imageUrl}" alt="Image générée" class="w-full h-96 object-cover">
            <div class="p-6">
                <p class="text-sm text-gray-600 dark:text-gray-400 mb-4"><strong class="text-gray-900 dark:text-white">Prompt:</strong> ${prompt}</p>
                <button onclick="downloadGeneratedImage('${imageUrl}', '${prompt}')" class="w-full px-6 py-3 bg-primary-600 hover:bg-primary-700 text-white rounded-xl font-semibold flex items-center justify-center gap-2 transition-all duration-300 hover:shadow-lg hover:shadow-primary-600/30">
                    <i class="fas fa-download"></i>
                    <span>Télécharger</span>
                </button>
            </div>
        </div>
    `;
}

function downloadGeneratedImage(imageUrl, prompt) {
    const a = document.createElement('a');
    a.href = imageUrl;
    a.download = `generated-${prompt.substring(0, 20).replace(/\s+/g, '-')}-${Date.now()}.jpg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('Téléchargement démarré', 'success');
}

// Modal
function openImageModal(imageData) {
    state.currentImage = imageData;
    elements.modalImage.src = imageData.url;
    elements.modalTitle.textContent = imageData.title;
    elements.modalDescription.textContent = imageData.description || '';
    elements.modal.classList.remove('hidden');
    elements.modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    elements.modal.classList.add('hidden');
    elements.modal.classList.remove('flex');
    document.body.style.overflow = '';

    setTimeout(() => {
        elements.modalImage.src = '';
        elements.modalTitle.textContent = '';
        elements.modalDescription.textContent = '';
        state.currentImage = null;
    }, 300);
}

async function downloadImage() {
    if (!state.currentImage) return;

    try {
        showToast('Préparation du téléchargement...', 'info');
        const a = document.createElement('a');
        a.href = state.currentImage.url;
        a.download = `seeker-${Date.now()}.jpg`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showToast('Téléchargement démarré', 'success');
    } catch (error) {
        console.error('Erreur de téléchargement:', error);
        window.open(state.currentImage.url, '_blank');
        showToast('Ouverture de l\'image dans un nouvel onglet', 'info');
    }
}

function shareImage() {
    if (!state.currentImage) return;

    if (navigator.share) {
        navigator.share({
            title: state.currentImage.title,
            text: state.currentImage.description,
            url: state.currentImage.url
        }).then(() => {
            showToast('Image partagée avec succès', 'success');
        }).catch(err => {
            console.error('Erreur de partage:', err);
            copyToClipboard(state.currentImage.url);
        });
    } else {
        copyToClipboard(state.currentImage.url);
    }
}

function generateSimilarImage() {
    if (!state.currentImage) return;

    const generateTab = document.querySelector('[data-tab="generate"]');
    if (generateTab) generateTab.click();

    elements.aiPrompt.value = state.currentImage.description || state.currentImage.title || 'Image similaire';
    closeModal();
    showToast('Prompt prérempli. Cliquez sur "Générer".', 'info');
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast('Lien copié dans le presse-papiers', 'success');
    }).catch(err => {
        console.error('Erreur de copie:', err);
        showToast('Impossible de copier le lien', 'error');
    });
}

// Utilitaires
function showLoader(loaderId) {
    const loader = document.getElementById(loaderId);
    if (loader) loader.classList.remove('hidden');
}

function hideLoader(loaderId) {
    const loader = document.getElementById(loaderId);
    if (loader) loader.classList.add('hidden');
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');

    const colors = {
        info: 'bg-blue-500',
        success: 'bg-green-500',
        warning: 'bg-yellow-500',
        error: 'bg-red-500'
    };

    const icons = {
        info: 'fa-info-circle',
        success: 'fa-check-circle',
        warning: 'fa-exclamation-triangle',
        error: 'fa-times-circle'
    };

    toast.className = `${colors[type]} text-white px-6 py-4 rounded-xl shadow-2xl flex items-center gap-3 min-w-[300px] max-w-md transform translate-x-full transition-transform duration-300 backdrop-blur-sm`;
    toast.innerHTML = `
        <i class="fas ${icons[type]} text-xl"></i>
        <span class="flex-1">${message}</span>
        <button onclick="this.parentElement.remove()" class="hover:bg-white/20 rounded-lg p-1 transition-colors">
            <i class="fas fa-times"></i>
        </button>
    `;

    container.appendChild(toast);
    setTimeout(() => toast.classList.remove('translate-x-full'), 100);

    setTimeout(() => {
        toast.classList.add('translate-x-full');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

window.downloadGeneratedImage = downloadGeneratedImage