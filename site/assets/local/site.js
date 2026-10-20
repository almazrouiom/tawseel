(() => {
  "use strict";

  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  };

  onReady(() => {
    /* Mobile navigation */
    const navToggle = document.querySelector("[data-nav-toggle]");
    const menu = document.getElementById("site-menu");
    if (navToggle && menu) {
      const closeMenu = () => {
        menu.classList.remove("is-open");
        navToggle.setAttribute("aria-expanded", "false");
      };
      navToggle.addEventListener("click", () => {
        const open = menu.classList.toggle("is-open");
        navToggle.setAttribute("aria-expanded", String(open));
      });
      menu.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeMenu));
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeMenu();
      });
    }

    /* Admin sidebar */
    const adminToggle = document.querySelector("[data-admin-toggle]");
    const adminSide = document.getElementById("admin-side");
    if (adminToggle && adminSide) {
      adminToggle.addEventListener("click", () => {
        const open = adminSide.classList.toggle("is-open");
        adminToggle.setAttribute("aria-expanded", String(open));
      });
      adminSide.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
          adminSide.classList.remove("is-open");
          adminToggle.setAttribute("aria-expanded", "false");
        });
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          adminSide.classList.remove("is-open");
          adminToggle.setAttribute("aria-expanded", "false");
        }
      });
    }

    /* OTP: digits only */
    document.querySelectorAll("[data-otp-input]").forEach((input) => {
      input.addEventListener("input", () => {
        input.value = input.value.replace(/\D/g, "").slice(0, 6);
      });
    });

    /* Resend cooldown */
    document.querySelectorAll("[data-resend-form]").forEach((form) => {
      const button = form.querySelector("[data-resend-button]");
      const counter = form.querySelector("[data-countdown]");
      if (!button) return;
      let remaining = Number.parseInt(form.dataset.cooldown || "0", 10);
      if (Number.isNaN(remaining)) remaining = 0;

      const tick = () => {
        if (remaining <= 0) {
          button.disabled = false;
          button.textContent = "إعادة إرسال الرمز";
          return;
        }
        button.disabled = true;
        if (counter) counter.textContent = String(remaining);
        remaining -= 1;
        window.setTimeout(tick, 1000);
      };
      tick();
    });

    /* Contact form: quote fields */
    document.querySelectorAll("[data-contact-form]").forEach((form) => {
      const radios = form.querySelectorAll('input[name="kind"]');
      const quoteFields = form.querySelector("[data-quote-fields]");
      if (!quoteFields || !radios.length) return;
      const update = () => {
        const selected = form.querySelector('input[name="kind"]:checked');
        const isQuote = selected && selected.value === "quote";
        quoteFields.hidden = !isQuote;
        quoteFields.querySelectorAll("input").forEach((input) => {
          input.required = false;
        });
      };
      radios.forEach((radio) => radio.addEventListener("change", update));
      update();
    });

    /* Prevent double submits */
    document.querySelectorAll("form[data-loading]").forEach((form) => {
      form.addEventListener("submit", () => {
        const button = form.querySelector('button[type="submit"]');
        if (!button) return;
        window.setTimeout(() => {
          button.disabled = true;
          button.classList.add("is-loading");
        }, 10);
      });
    });

    /* Copy shipment code */
    document.querySelectorAll("[data-copy]").forEach((button) => {
      button.addEventListener("click", async () => {
        const value = button.dataset.copy || "";
        if (!value) return;
        try {
          if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(value);
          } else {
            const area = document.createElement("textarea");
            area.value = value;
            area.setAttribute("readonly", "");
            area.style.position = "fixed";
            area.style.opacity = "0";
            document.body.appendChild(area);
            area.select();
            document.execCommand("copy");
            area.remove();
          }
          const previous = button.getAttribute("aria-label");
          button.setAttribute("aria-label", "تم النسخ");
          button.classList.add("is-copied");
          window.setTimeout(() => {
            button.setAttribute("aria-label", previous || "نسخ");
            button.classList.remove("is-copied");
          }, 1800);
        } catch (error) {
          /* Clipboard permissions are optional. */
        }
      });
    });

    /* Print buttons */
    document.querySelectorAll("[data-print]").forEach((button) => {
      button.addEventListener("click", () => window.print());
    });

    /* Confirm destructive/state actions */
    document.querySelectorAll("[data-confirm]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const message = form.dataset.confirm || "هل تريد المتابعة؟";
        if (!window.confirm(message)) {
          event.preventDefault();
        }
      });
    });
  });
})();
