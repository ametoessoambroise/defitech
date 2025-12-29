/**
 * Cloudinary Global Uploader Helper
 * Handles uploading files to Cloudinary using unsigned presets.
 */

// Vérifier si les variables existent déjà avant de les déclarer
if (typeof window.CLOUDINARY_CLOUD_NAME === 'undefined') {
    window.CLOUDINARY_CLOUD_NAME = 'dmokvhpjt'; // Your Cloud name
}

if (typeof window.CLOUDINARY_UPLOAD_URL === 'undefined') {
    window.CLOUDINARY_UPLOAD_URL = `https://api.cloudinary.com/v1_1/${window.CLOUDINARY_CLOUD_NAME}/upload`;
}

/**
 * Uploads a file to Cloudinary.
 * @param {File} file - The file object from input[type="file"]
 * @param {string} uploadPreset - The name of the unsigned upload preset
 * @param {string} resourceType - 'image', 'raw', or 'auto' (default: 'auto')
 * @returns {Promise<object>} - The Cloudinary response object (containing secure_url, public_id, etc.)
 */
async function uploadToCloudinary(file, uploadPreset, resourceType = 'auto') {
    if (!file) throw new Error("Veuillez sélectionner un fichier.");

    const formData = new FormData();
    formData.append("file", file);
    formData.append("upload_preset", uploadPreset);

    try {
        const response = await fetch(CLOUDINARY_UPLOAD_URL.replace('upload', `${resourceType}/upload`), {
            method: "POST",
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error.message || "Erreur lors de l'upload");
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error("Erreur lors de l'upload sur Cloudinary:", error);
        throw error;
    }
}

/**
 * Helper to attach upload behavior to a form input.
 * @param {string} inputId - ID of the file input
 * @param {string} hiddenInputId - ID of the hidden input to store the URL
 * @param {string} preset - Upload preset name
 * @param {string} feedbackElementId - (Optional) ID of element to show status/preview
 * @param {string} resourceType - (Optional) 'image', 'raw', 'auto'
 */
function attachCloudinaryUpload(inputId, hiddenInputId, preset, feedbackElementId = null, resourceType = 'auto') {
    const fileInput = document.getElementById(inputId);
    const hiddenInput = document.getElementById(hiddenInputId);
    const feedback = feedbackElementId ? document.getElementById(feedbackElementId) : null;

    if (!fileInput || !hiddenInput) {
        console.warn(` (${inputId}, ${hiddenInputId})`);
        return;
    }

    fileInput.addEventListener('change', async () => {
        const file = fileInput.files[0];
        if (!file) return;

        if (feedback) feedback.textContent = "Téléchargement en cours...";

        try {
            const result = await uploadToCloudinary(file, preset, resourceType);
            hiddenInput.value = result.secure_url;
            console.log("File uploaded:", result.secure_url);

            if (feedback) {
                feedback.innerHTML = `✅ Fichier prêt! <a href="${result.secure_url}" target="_blank">Voir</a>`;
                // Preview if image
                if (resourceType === 'image' || file.type.startsWith('image/')) {
                    const img = document.createElement('img');
                    img.src = result.secure_url;
                    img.style.maxWidth = '100px';
                    img.style.display = 'block';
                    img.style.marginTop = '5px';
                    feedback.appendChild(img);
                }
            }
        } catch (error) {
            if (feedback) feedback.textContent = "❌ " + error.message;
            alert("Erreur lors de l'upload: " + error.message);
            fileInput.value = ""; // Clear input
        }
    });
}
