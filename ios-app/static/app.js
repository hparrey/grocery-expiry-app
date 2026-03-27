function toggleCustomCategory() {
    const categorySelect = document.getElementById("item-category");
    const customCategoryInput = document.getElementById("custom-category");

    if (!categorySelect || !customCategoryInput) return;

    if (categorySelect.value === "Other") {
        customCategoryInput.style.display = "block";
        customCategoryInput.required = true;
    } else {
        customCategoryInput.style.display = "none";
        customCategoryInput.required = false;
        customCategoryInput.value = "";
    }
}

function previewExpiryPhoto() {
    const fileInput = document.getElementById("expiry-photo");
    const preview = document.getElementById("expiry-preview");
    const status = document.getElementById("ocr-status");

    if (!fileInput || !preview || !status) return;

    if (!fileInput.files || fileInput.files.length === 0) {
        preview.style.display = "none";
        preview.src = "";
        return;
    }

    const file = fileInput.files[0];
    const imageUrl = URL.createObjectURL(file);

    preview.src = imageUrl;
    preview.style.display = "block";
    status.textContent = "Photo selected. Tap 'Read Expiration Date' to extract details.";
}

async function readExpiryPhoto() {
    const fileInput = document.getElementById("expiry-photo");
    const status = document.getElementById("ocr-status");
    const expirationInput = document.getElementById("item-expiration");
    const categorySelect = document.getElementById("item-category");
    const customCategoryInput = document.getElementById("custom-category");

    if (!fileInput || !status || !expirationInput) return;

    if (!fileInput.files || fileInput.files.length === 0) {
        status.textContent = "Please take or choose a photo first.";
        return;
    }

    const file = fileInput.files[0];
    status.textContent = "Uploading image and extracting data...";

    try {
        const formData = new FormData();
        formData.append("file", file);

        const response = await fetch("/extract-date/", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (data.error) {
            status.textContent = "Error: " + data.error;
            return;
        }

        // Expiration date
        if (data.expiration_date) {
            const [month, day, year] = data.expiration_date.split("-");
            const isoDate = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
            expirationInput.value = isoDate;

            status.textContent = `Expiration date detected: ${data.expiration_date}`;
        } else {
            status.textContent = "Could not detect expiration date.";
        }

        // Product type → category autofill
        if (data.product_type && categorySelect && customCategoryInput) {
            const detected = data.product_type.trim();

            let matched = false;
            for (let option of categorySelect.options) {
                if (option.value.toLowerCase() === detected.toLowerCase()) {
                    categorySelect.value = option.value;
                    matched = true;
                    break;
                }
            }

            if (!matched) {
                categorySelect.value = "Other";
                customCategoryInput.style.display = "block";
                customCategoryInput.required = true;
                customCategoryInput.value = detected;
            }
        }

    } catch (error) {
        console.error("Request failed:", error);
        status.textContent = "Failed to process image. Try again.";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    toggleCustomCategory();
});