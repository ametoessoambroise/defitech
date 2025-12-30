// Real-time Notification System for DEFITECH
// Version 2.0.0 - Modernized

class NotificationManager {
  constructor() {
    this.notifications = [];
    this.unreadCount = 0;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 3000;
    this.notificationSound = null;
    this.csrfToken = null;

    this.init();
  }

  getCSRFToken() {
    if (!this.csrfToken) {
      const metaTag = document.querySelector('meta[name="csrf-token"]');
      this.csrfToken = metaTag ? metaTag.getAttribute("content") : "";
    }
    return this.csrfToken;
  }

  init() {
    this.loadSettings();
    this.initializeUI();
    this.loadNotifications();
    this.startPolling();
    this.setupEventListeners();

    // Initialize notification sound
    this.notificationSound = new Audio("/static/sounds/notification.mp3");
    this.notificationSound.volume = 0.5;
  }

  loadSettings() {
    this.settings = {
      soundEnabled: localStorage.getItem("notif_sound") !== "false",
      desktopEnabled: localStorage.getItem("notif_desktop") === "true",
      autoMarkAsRead: localStorage.getItem("notif_auto_mark") === "true",
      pollInterval:
        parseInt(localStorage.getItem("notif_poll_interval")) || 30000,
    };
  }

  initializeUI() {
    const notifBell = document.getElementById("notification-bell");
    const notifBadge = document.getElementById("notification-badge");
    const notifDropdown = document.getElementById("notification-dropdown");

    if (!notifBell || !notifBadge || !notifDropdown) {
      console.warn("Notification UI elements not found");
      return;
    }

    notifBell.addEventListener("click", (e) => {
      e.stopPropagation();
      this.toggleDropdown();
    });

    document.addEventListener("click", (e) => {
      if (!notifDropdown.contains(e.target) && !notifBell.contains(e.target)) {
        this.closeDropdown();
      }
    });
  }

  setupEventListeners() {
    const markAllBtn = document.getElementById("mark-all-read");
    if (markAllBtn) {
      markAllBtn.addEventListener("click", () => this.markAllAsRead());
    }

    const clearAllBtn = document.getElementById("clear-all-notifications");
    if (clearAllBtn) {
      clearAllBtn.addEventListener("click", () => this.clearAll());
    }

    const settingsBtn = document.getElementById("notification-settings-btn");
    if (settingsBtn) {
      settingsBtn.addEventListener("click", () => this.openSettings());
    }

    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        this.loadNotifications();
      }
    });
  }

  async loadNotifications() {
    try {
      const response = await fetch("/notifications/api", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
      });

      if (!response.ok) {
        throw new Error("Failed to load notifications");
      }

      const data = await response.json();
      this.notifications = data.notifications || [];
      this.unreadCount = data.unread_count || 0;

      this.updateUI();
      this.updateBadge();
    } catch (error) {
      console.error("Error loading notifications:", error);
      this.showEmptyState("error");
    }
  }

  updateUI() {
    const container = document.getElementById("notification-list");
    if (!container) return;

    if (this.notifications.length === 0) {
      this.showEmptyState("empty");
      return;
    }

    container.innerHTML = this.notifications
      .map((notif) => this.renderNotification(notif))
      .join("");

    container.querySelectorAll("[data-notification-id]").forEach((item) => {
      item.addEventListener("click", (e) => {
        const id = e.currentTarget.dataset.notificationId;
        this.handleNotificationClick(id);
      });

      const deleteBtn = item.querySelector(".delete-notification");
      if (deleteBtn) {
        deleteBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const id = e.currentTarget.closest("[data-notification-id]").dataset
            .notificationId;
          this.deleteNotification(id);
        });
      }
    });
  }

  renderNotification(notif) {
    const isUnread = !notif.est_lue;
    const icon = this.getNotificationIcon(notif.type);
    const colors = this.getNotificationColors(notif.type);
    const timeAgo = this.getTimeAgo(notif.date_creation);

    return `
      <div class="notification-item ${isUnread ? "unread" : ""}"
           data-notification-id="${notif.id}"
           data-notification-url="${notif.lien || "#"}">
        <div class="group flex items-start gap-4 px-6 py-4 hover:bg-gradient-to-r ${colors.hover} cursor-pointer transition-all duration-300 ${isUnread ? colors.bg : ""}">
          <div class="flex-shrink-0">
            <div class="w-12 h-12 rounded-xl ${colors.icon} flex items-center justify-center shadow-lg group-hover:scale-110 group-hover:rotate-3 transition-all duration-300">
              <i class="${icon} text-white text-lg"></i>
            </div>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-start justify-between gap-2 mb-2">
              <p class="text-sm font-bold text-gray-900 ${isUnread ? "font-extrabold" : ""}">
                ${this.escapeHtml(notif.titre)}
              </p>
              ${isUnread ? '<span class="flex-shrink-0 w-2.5 h-2.5 bg-blue-600 rounded-full animate-pulse shadow-lg shadow-blue-500/50"></span>' : ""}
            </div>
            <p class="text-sm text-gray-600 line-clamp-2 mb-3">
              ${this.escapeHtml(notif.message)}
            </p>
            <div class="flex items-center justify-between">
              <span class="inline-flex items-center text-xs font-semibold text-gray-500 px-2.5 py-1 bg-gray-100 rounded-lg">
                <i class="far fa-clock mr-1.5"></i>
                ${timeAgo}
              </span>
              <button class="delete-notification text-gray-400 hover:text-red-600 transition-colors p-2 rounded-lg hover:bg-red-50 active:scale-95">
                <i class="fas fa-trash text-xs"></i>
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  getNotificationIcon(type) {
    const icons = {
      info: "fas fa-info-circle",
      success: "fas fa-check-circle",
      warning: "fas fa-exclamation-triangle",
      error: "fas fa-times-circle",
      message: "fas fa-envelope",
      assignment: "fas fa-clipboard-list",
      grade: "fas fa-star",
      announcement: "fas fa-bullhorn",
      reminder: "fas fa-bell",
      system: "fas fa-cog",
    };
    return icons[type] || "fas fa-bell";
  }

  getNotificationColors(type) {
    const colors = {
      info: {
        bg: "bg-gradient-to-r from-blue-50 to-indigo-50",
        icon: "bg-gradient-to-br from-blue-500 to-indigo-600",
        hover: "hover:from-blue-100 hover:to-indigo-100",
      },
      success: {
        bg: "bg-gradient-to-r from-green-50 to-emerald-50",
        icon: "bg-gradient-to-br from-green-500 to-emerald-600",
        hover: "hover:from-green-100 hover:to-emerald-100",
      },
      warning: {
        bg: "bg-gradient-to-r from-yellow-50 to-orange-50",
        icon: "bg-gradient-to-br from-yellow-500 to-orange-600",
        hover: "hover:from-yellow-100 hover:to-orange-100",
      },
      error: {
        bg: "bg-gradient-to-r from-red-50 to-pink-50",
        icon: "bg-gradient-to-br from-red-500 to-pink-600",
        hover: "hover:from-red-100 hover:to-pink-100",
      },
      message: {
        bg: "bg-gradient-to-r from-purple-50 to-pink-50",
        icon: "bg-gradient-to-br from-purple-500 to-pink-600",
        hover: "hover:from-purple-100 hover:to-pink-100",
      },
    };
    return colors[type] || colors.info;
  }

  getTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return "À l'instant";
    if (seconds < 3600) return `Il y a ${Math.floor(seconds / 60)} min`;
    if (seconds < 86400) return `Il y a ${Math.floor(seconds / 3600)}h`;
    if (seconds < 604800) return `Il y a ${Math.floor(seconds / 86400)}j`;

    return date.toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "short",
      year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
    });
  }

  updateBadge() {
    const badge = document.getElementById("notification-badge");
    const pulse = document.getElementById("notification-pulse");

    if (!badge) return;

    if (this.unreadCount > 0) {
      badge.textContent = this.unreadCount > 99 ? "99+" : this.unreadCount;
      badge.classList.remove("hidden");
      if (pulse) pulse.classList.remove("hidden");

      if (!document.hidden) {
        document.title = `(${this.unreadCount}) DEFITECH`;
      }
    } else {
      badge.classList.add("hidden");
      if (pulse) pulse.classList.add("hidden");
      document.title = "DEFITECH";
    }
  }

  async handleNotificationClick(id) {
    const notification = this.notifications.find((n) => n.id == id);
    if (!notification) return;

    if (this.settings.autoMarkAsRead && !notification.est_lue) {
      await this.markAsRead(id);
    }

    if (notification.lien) {
      window.location.href = notification.lien;
    }
  }

  async markAsRead(id) {
    try {
      const response = await fetch(`/api/notifications/${id}/mark-read`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        credentials: "same-origin",
      });

      if (response.ok) {
        const notif = this.notifications.find((n) => n.id == id);
        if (notif && !notif.est_lue) {
          notif.est_lue = true;
          this.unreadCount = Math.max(0, this.unreadCount - 1);
          this.updateUI();
          this.updateBadge();
        }
      }
    } catch (error) {
      console.error("Error marking notification as read:", error);
    }
  }

  async markAllAsRead() {
    try {
      const response = await fetch("/notifications/api/mark-all-read", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        credentials: "same-origin",
      });

      if (response.ok) {
        this.notifications.forEach((n) => (n.est_lue = true));
        this.unreadCount = 0;
        this.updateUI();
        this.updateBadge();
        this.showToast(
          "Toutes les notifications ont été marquées comme lues",
          "success",
        );
      }
    } catch (error) {
      console.error("Error marking all as read:", error);
      this.showToast("Erreur lors du marquage des notifications", "error");
    }
  }

  async deleteNotification(id) {
    try {
      const response = await fetch(`/api/notifications/${id}`, {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        credentials: "same-origin",
      });

      if (response.ok) {
        const index = this.notifications.findIndex((n) => n.id == id);
        if (index > -1) {
          const wasUnread = !this.notifications[index].est_lue;
          this.notifications.splice(index, 1);
          if (wasUnread) {
            this.unreadCount = Math.max(0, this.unreadCount - 1);
          }
          this.updateUI();
          this.updateBadge();
        }
      }
    } catch (error) {
      console.error("Error deleting notification:", error);
    }
  }

  async clearAll() {
    if (
      !confirm("Êtes-vous sûr de vouloir supprimer toutes les notifications ?")
    ) {
      return;
    }

    try {
      const response = await fetch("/notifications/api/clear-all", {
        method: "DELETE",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
        credentials: "same-origin",
      });

      if (response.ok) {
        this.notifications = [];
        this.unreadCount = 0;
        this.updateUI();
        this.updateBadge();
        this.showToast(
          "Toutes les notifications ont été supprimées",
          "success",
        );
      }
    } catch (error) {
      console.error("Error clearing notifications:", error);
      this.showToast("Erreur lors de la suppression", "error");
    }
  }

  toggleDropdown() {
    const dropdown = document.getElementById("notification-dropdown");
    if (!dropdown) return;

    dropdown.classList.toggle("hidden");

    if (!dropdown.classList.contains("hidden")) {
      this.loadNotifications();
    }
  }

  closeDropdown() {
    const dropdown = document.getElementById("notification-dropdown");
    if (dropdown) {
      dropdown.classList.add("hidden");
    }
  }

  startPolling() {
    setInterval(() => {
      if (!document.hidden) {
        this.checkForNewNotifications();
      }
    }, this.settings.pollInterval);
  }

  async checkForNewNotifications() {
    try {
      const response = await fetch("/notifications/api/count", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
        cache: "no-cache",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": this.getCSRFToken(),
        },
      });

      if (!response.ok) return;

      const data = await response.json();
      const newCount = data.unread_count || 0;

      if (newCount > this.unreadCount) {
        this.loadNotifications();
        this.playNotificationSound();
        this.showDesktopNotification(data.latest);
      }
    } catch (error) {
      console.error("Error checking for new notifications:", error);
    }
  }

  playNotificationSound() {
    if (this.settings.soundEnabled && this.notificationSound) {
      this.notificationSound.play().catch((err) => {
        console.log("Could not play notification sound:", err);
      });
    }
  }

  showDesktopNotification(notification) {
    if (!this.settings.desktopEnabled || !notification) return;

    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(notification.titre, {
        body: notification.message,
        icon: "/static/images/icons/icon-192x192.png",
        badge: "/static/images/icons/icon-72x72.png",
        tag: `notification-${notification.id}`,
        requireInteraction: false,
      });
    }
  }

  async requestDesktopPermission() {
    if ("Notification" in window && Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission === "granted") {
        this.settings.desktopEnabled = true;
        localStorage.setItem("notif_desktop", "true");
        this.showToast("Notifications de bureau activées", "success");
      }
    }
  }

  openSettings() {
    const modal = document.getElementById("notification-settings-modal");
    if (modal) {
      modal.classList.remove("hidden");
      this.loadSettingsUI();
    }
  }

  loadSettingsUI() {
    const soundToggle = document.getElementById("notif-sound-toggle");
    const desktopToggle = document.getElementById("notif-desktop-toggle");
    const autoMarkToggle = document.getElementById("notif-auto-mark-toggle");

    if (soundToggle) soundToggle.checked = this.settings.soundEnabled;
    if (desktopToggle) desktopToggle.checked = this.settings.desktopEnabled;
    if (autoMarkToggle) autoMarkToggle.checked = this.settings.autoMarkAsRead;
  }

  saveSettings(newSettings) {
    this.settings = { ...this.settings, ...newSettings };

    localStorage.setItem("notif_sound", this.settings.soundEnabled);
    localStorage.setItem("notif_desktop", this.settings.desktopEnabled);
    localStorage.setItem("notif_auto_mark", this.settings.autoMarkAsRead);

    this.showToast("Paramètres enregistrés", "success");
  }

  showEmptyState(type = "empty") {
    const container = document.getElementById("notification-list");
    if (!container) return;

    const states = {
      empty: {
        icon: "fas fa-bell-slash",
        title: "Aucune notification",
        message: "Vous êtes à jour !",
        color: "gray",
      },
      error: {
        icon: "fas fa-exclamation-triangle",
        title: "Erreur de chargement",
        message: "Impossible de charger les notifications",
        color: "red",
      },
    };

    const state = states[type] || states.empty;

    container.innerHTML = `
      <div class="flex flex-col items-center justify-center py-16 px-4">
        <div class="w-20 h-20 rounded-full bg-gradient-to-br from-${state.color}-100 to-${state.color}-200 flex items-center justify-center mb-4 shadow-lg">
          <i class="${state.icon} text-${state.color}-500 text-3xl"></i>
        </div>
        <p class="text-sm font-bold text-gray-900 mb-1">${state.title}</p>
        <p class="text-xs text-gray-500">${state.message}</p>
      </div>
    `;
  }

  showToast(message, type = "info") {
    const toast = document.createElement("div");
    const colors = {
      success: "from-green-500 to-emerald-600",
      error: "from-red-500 to-pink-600",
      warning: "from-yellow-500 to-orange-600",
      info: "from-blue-500 to-indigo-600",
    };

    toast.className = `fixed bottom-4 right-4 px-6 py-4 rounded-2xl shadow-2xl text-white z-50 animate-slide-in-up bg-gradient-to-r ${colors[type] || colors.info} max-w-sm flex items-center space-x-3`;

    const icons = {
      success: "fa-check-circle",
      error: "fa-times-circle",
      warning: "fa-exclamation-triangle",
      info: "fa-info-circle",
    };

    toast.innerHTML = `
      <i class="fas ${icons[type] || icons.info} text-xl"></i>
      <span class="font-semibold">${message}</span>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
      toast.classList.add("animate-fade-out");
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

// Initialize notification manager
const notificationManager = new NotificationManager();

// Export for global use
window.NotificationManager = notificationManager;
