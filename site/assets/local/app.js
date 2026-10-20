(function () {
  "use strict";

  // Keep the current year in the footer without editing every page.
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  // Normalize the phone field while preserving the user's ability to type it.
  var phone = document.querySelector('input[name="phone"]');
  if (phone) {
    phone.addEventListener("input", function () {
      phone.value = phone.value
        .replace(/[٠-٩]/g, function (digit) {
          return String.fromCharCode(digit.charCodeAt(0) - 0x0660);
        })
        .replace(/[^\d+\s-]/g, "");
    });
    phone.addEventListener("blur", function () {
      phone.value = phone.value.trim();
    });
  }

  // Tracking codes are Latin letters and digits; normalize what people paste.
  document.querySelectorAll('input[name="code"]').forEach(function (input) {
    input.addEventListener("blur", function () {
      input.value = input.value.replace(/\s+/g, "").replace(/^#/, "").toUpperCase();
    });
  });

  // The OTP is always six digits.
  var otp = document.querySelector('input[name="code"][data-otp]');
  if (otp) {
    otp.addEventListener("input", function () {
      otp.value = otp.value.replace(/\D/g, "").slice(0, 6);
    });
  }

  // Prevent double submits and show progress on slow connections.
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function () {
      if (form.dataset.submitting === "1") {
        return;
      }
      form.dataset.submitting = "1";
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
        button.disabled = true;
        if (button.tagName === "BUTTON") {
          var original = button.innerHTML;
          button.dataset.original = original;
          button.innerHTML = '<span class="spinner-border spinner-border-sm align-middle mr-2" role="status" aria-hidden="true"></span>' + original;
        }
      });
      // Re-enable if the browser restores this page from the back/forward cache.
      window.setTimeout(function () {
        form.dataset.submitting = "0";
      }, 15000);
    });
  });

  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-loading]").forEach(function (form) {
      form.dataset.submitting = "0";
      form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (button) {
        button.disabled = false;
        if (button.tagName === "BUTTON" && button.dataset.original) {
          button.innerHTML = button.dataset.original;
        }
      });
    });
  });

  // Arabic validation messages for the two public forms.
  document.querySelectorAll("form[data-ar-validation]").forEach(function (form) {
    form.addEventListener("submit", function () {
      form.querySelectorAll("input[required]").forEach(function (input) {
        if (!input.value.trim()) {
          input.setCustomValidity("يرجى تعبئة هذا الحقل.");
        } else {
          input.setCustomValidity("");
        }
      });
    });
    form.querySelectorAll("input").forEach(function (input) {
      input.addEventListener("input", function () {
        input.setCustomValidity("");
      });
    });
  });
})();
