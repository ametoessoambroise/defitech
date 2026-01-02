/**
 * AppLock - Gestionnaire de verrouillage PWA
 */
const AppLock = {
    digits: [],
    config: {
        pinLength: 6, // Autorise jusqu'à 6
        statusUrl: '/api/app-lock/status',
        verifyUrl: '/api/app-lock/verify-pin',
        verifyPasswordUrl: '/api/app-lock/verify-password',
        logoutUrl: '/auth/logout'
    },
    state: {
        isEnabled: false,
        isLocked: false,
        lastActivity: Date.now(),
        isVerifying: false
    },

    async init() {
        // Ne rien faire si on est sur la page de login ou register
        if (window.location.pathname === '/login' || window.location.pathname === '/register') return;

        try {
            const resp = await fetch(this.config.statusUrl);
            const data = await resp.json();

            if (resp.status === 401) return; // Non connecté

            this.state.isEnabled = data.enabled;
            this.state.isLocked = data.is_locked;

            if (this.state.isEnabled) {
                if (this.state.isLocked) {
                    this.showOverlay();
                }
                this.setupInactivityCheck();
                this.setupVisibilityChange();
            }

            if (data.biometric_enabled) {
                document.getElementById('biometricBtn')?.classList.remove('hidden');
            }
        } catch (err) {
            console.error('AppLock Error:', err);
        }
    },

    setupVisibilityChange() {
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                this.checkLockStatus();
            }
        });
        window.addEventListener('pageshow', () => this.checkLockStatus());
    },

    async checkLockStatus() {
        if (!this.state.isEnabled) return;

        try {
            const resp = await fetch(this.config.statusUrl);
            const data = await resp.json();
            if (data.is_locked) {
                this.showOverlay();
            }
        } catch (err) {
            console.error('AppLock Sync Error:', err);
        }
    },

    setupInactivityCheck() {
        // Sur mobile, visibilitychange est plus fiable que mousemove
        // On garde un petit intervalle pour verrouiller si l'app reste ouverte au premier plan
        setInterval(() => {
            const idleTime = (Date.now() - this.state.lastActivity) / 60000;
            // On peut ajouter ici un check de timeout si besoin
        }, 30000);

        const resetTimer = () => { this.state.lastActivity = Date.now(); };
        document.addEventListener('touchstart', resetTimer);
        document.addEventListener('click', resetTimer);
        document.addEventListener('keydown', resetTimer);
    },

    appendDigit(digit) {
        if (this.digits.length >= this.config.pinLength) return;

        this.digits.push(digit);
        this.updateDots();

        // Affiche le bouton "Valider" si on a au moins 4 chiffres
        const validateBtn = document.getElementById('validatePinBtn');
        if (this.digits.length >= 4) {
            validateBtn?.classList.remove('hidden');
        }

        if (this.digits.length === this.config.pinLength) {
            // Auto-verify à 6 chiffres
            if (!this.state.isVerifying) {
                setTimeout(() => this.verifyPIN(), 200);
            }
        }
    },

    clearDigits() {
        this.digits = [];
        this.updateDots();
        document.getElementById('validatePinBtn')?.classList.add('hidden');
    },

    updateDots() {
        const dots = document.querySelectorAll('#pinDots div');
        dots.forEach((dot, i) => {
            if (i < this.digits.length) {
                dot.classList.add('pin-dot-active');
            } else {
                dot.classList.remove('pin-dot-active');
            }
        });
    },

    async verifyPIN() {
        if (this.state.isVerifying) return;
        const pin = this.digits.join('');
        if (pin.length < 4) return;

        this.state.isVerifying = true;
        const overlayContent = document.querySelector('#appLockOverlay > div');
        const statusMsg = document.getElementById('lockStatusMessage');
        const validateBtn = document.getElementById('validatePinBtn');

        if (validateBtn) {
            validateBtn.disabled = true;
            validateBtn.textContent = 'Vérification...';
        }

        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content ||
                document.querySelector('input[name="csrf_token"]')?.value;

            const resp = await fetch(this.config.verifyUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ pin })
            });

            const data = await resp.json();

            if (data.success) {
                this.hideOverlay();
                this.state.isLocked = false;
                this.state.lastActivity = Date.now();
                this.clearDigits();
            } else {
                // Animation d'erreur
                overlayContent?.classList.add('pin-shake');
                if (statusMsg) {
                    statusMsg.textContent = data.message || 'Code PIN incorrect';
                    statusMsg.classList.add('text-red-500');
                }

                setTimeout(() => {
                    overlayContent?.classList.remove('pin-shake');
                    this.clearDigits();
                    setTimeout(() => {
                        if (statusMsg) {
                            statusMsg.textContent = 'Entrez votre code PIN pour continuer';
                            statusMsg.classList.remove('text-red-500');
                        }
                    }, 1000);
                }, 400);
            }
        } catch (err) {
            console.error('Verification Error:', err);
            if (statusMsg) {
                statusMsg.textContent = 'Erreur lors de la vérification';
                statusMsg.classList.add('text-red-500');
            }
        } finally {
            this.state.isVerifying = false;
            if (validateBtn) {
                validateBtn.disabled = false;
                validateBtn.textContent = 'Valider le PIN';
            }
        }
    },

    showPasswordForm() {
        document.getElementById('keypadContainer').classList.add('hidden');
        document.getElementById('pinDots').classList.add('hidden');
        document.getElementById('passwordFallbackForm').classList.remove('hidden');
        document.getElementById('togglePasswordFormBtn').classList.add('hidden');
        document.getElementById('lockStatusMessage').textContent = 'Vérification par mot de passe';
    },

    hidePasswordForm() {
        document.getElementById('keypadContainer').classList.remove('hidden');
        document.getElementById('pinDots').classList.remove('hidden');
        document.getElementById('passwordFallbackForm').classList.add('hidden');
        document.getElementById('togglePasswordFormBtn').classList.remove('hidden');
        document.getElementById('lockStatusMessage').textContent = 'Entrez votre code PIN pour continuer';
        document.getElementById('fallbackPasswordInput').value = '';
    },

    async verifyPassword() {
        const password = document.getElementById('fallbackPasswordInput').value;
        const statusMsg = document.getElementById('lockStatusMessage');

        if (!password) return;

        try {
            const resp = await fetch(this.config.verifyPasswordUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content
                },
                body: JSON.stringify({ password })
            });

            const data = await resp.json();

            if (data.success) {
                this.hideOverlay();
                this.state.isLocked = false;
                this.state.lastActivity = Date.now();
                this.hidePasswordForm();
            } else {
                statusMsg.textContent = data.message || 'Mot de passe incorrect';
                statusMsg.classList.add('text-red-500');
                setTimeout(() => {
                    statusMsg.classList.remove('text-red-500');
                    statusMsg.textContent = 'Vérification par mot de passe';
                }, 2000);
            }
        } catch (err) {
            console.error('Password Verification Error:', err);
        }
    },

    showOverlay() {
        const overlay = document.getElementById('appLockOverlay');
        if (!overlay) return;

        overlay.classList.remove('hidden');
        setTimeout(() => overlay.classList.remove('opacity-0'), 10);
        this.clearDigits();
        this.state.isLocked = true;
    },

    hideOverlay() {
        const overlay = document.getElementById('appLockOverlay');
        if (!overlay) return;

        overlay.classList.add('opacity-0');
        setTimeout(() => overlay.classList.add('hidden'), 300);
    },

    async useBiometrics() {
        const statusMsg = document.getElementById('lockStatusMessage');
        const biometricBtn = document.getElementById('biometricBtn');

        try {
            biometricBtn.classList.add('animate-pulse');

            // 1. Obtenir les options d'authentification
            const resp = await fetch('/api/app-lock/webauthn/login-options');
            const options = await resp.json();

            if (!resp.ok) throw new Error(options.message);

            // 2. Préparer les options (Base64 -> ArrayBuffer)
            options.challenge = this._bufferDecode(options.challenge);
            if (options.allowCredentials) {
                options.allowCredentials.forEach(c => c.id = this._bufferDecode(c.id));
            }

            // 3. Demander l'authentification au navigateur
            const assertion = await navigator.credentials.get({ publicKey: options });

            // 4. Préparer la réponse (ArrayBuffer -> Base64)
            const assertionJSON = {
                id: assertion.id,
                rawId: this._bufferEncode(assertion.rawId),
                type: assertion.type,
                response: {
                    authenticatorData: this._bufferEncode(assertion.response.authenticatorData),
                    clientDataJSON: this._bufferEncode(assertion.response.clientDataJSON),
                    signature: this._bufferEncode(assertion.response.signature),
                    userHandle: assertion.response.userHandle ? this._bufferEncode(assertion.response.userHandle) : null,
                },
            };

            // 5. Vérifier la réponse côté serveur
            const verifyResp = await fetch('/api/app-lock/webauthn/login-verify', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content
                },
                body: JSON.stringify(assertionJSON)
            });

            const result = await verifyResp.json();

            if (result.success) {
                this.hideOverlay();
                this.state.isLocked = false;
                this.state.lastActivity = Date.now();
            } else {
                throw new Error(result.message);
            }

        } catch (err) {
            console.error('Biometric Auth Error:', err);
            statusMsg.textContent = err.message || 'Échec de la biométrie';
            statusMsg.classList.add('text-red-500');
            setTimeout(() => {
                statusMsg.textContent = 'Entrez votre code PIN pour continuer';
                statusMsg.classList.remove('text-red-500');
            }, 3000);
        } finally {
            biometricBtn.classList.remove('animate-pulse');
        }
    },

    // Helpers privés pour WebAuthn
    _bufferDecode(value) {
        return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
    },

    _bufferEncode(value) {
        return btoa(String.fromCharCode.apply(null, new Uint8Array(value)))
            .replace(/\+/g, "-")
            .replace(/\//g, "_")
            .replace(/=/g, "");
    },

    logout() {
        window.location.href = this.config.logoutUrl;
    }
};

// Initialisation au chargement
document.addEventListener('DOMContentLoaded', () => AppLock.init());
