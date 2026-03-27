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
    status.textContent = "Photo selected. Tap 'Read Expiration Date' to extract the date.";
}

async function readExpiryPhoto() {
    const fileInput = document.getElementById("expiry-photo");
    const status = document.getElementById("ocr-status");
    const expirationInput = document.getElementById("item-expiration");

    if (!fileInput || !status || !expirationInput) return;

    if (!fileInput.files || fileInput.files.length === 0) {
        status.textContent = "Please take or choose a photo first.";
        return;
    }

    const file = fileInput.files[0];
    status.textContent = "Reading expiration date...";

    try {
        const result = await Tesseract.recognize(file, "eng", {
            logger: (message) => {
                if (
                    message.status === "recognizing text" &&
                    typeof message.progress === "number"
                ) {
                    const percent = Math.round(message.progress * 100);
                    status.textContent = `Reading expiration date... ${percent}%`;
                }
            }
        });

        const text = result?.data?.text || "";
        console.log("OCR text:", text);

        const extractedDate = extractDateFromText(text);

        if (extractedDate) {
            expirationInput.value = extractedDate;
            status.textContent = `Expiration date detected: ${formatForDisplay(extractedDate)}. You can still edit it manually.`;
        } else {
            status.textContent = "Could not confidently detect a date. Please enter it manually.";
        }
    } catch (error) {
        console.error("OCR failed:", error);
        status.textContent = "OCR failed. Please enter the date manually.";
    }
}

function extractDateFromText(rawText) {
    if (!rawText) return null;

    let text = rawText.toUpperCase();

    text = text
        .replace(/O/g, "0")
        .replace(/I/g, "1")
        .replace(/L/g, "1")
        .replace(/\|/g, "1")
        .replace(/,/g, " ")
        .replace(/\s+/g, " ")
        .trim();

    text = text
        .replace(/BEST BY/g, "EXP")
        .replace(/USE BY/g, "EXP")
        .replace(/SELL BY/g, "EXP")
        .replace(/BB/g, "EXP");

    let match;

    match = text.match(/(?:EXP\s*)?(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})/);
    if (match) {
        let month = match[1];
        let day = match[2];
        let year = match[3];

        if (year.length === 2) year = "20" + year;
        return toIsoDate(year, month, day);
    }

    match = text.match(/(?:EXP\s*)?(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})/);
    if (match) {
        const year = match[1];
        const month = match[2];
        const day = match[3];
        return toIsoDate(year, month, day);
    }

    const monthNames = {
        JAN: "01",
        FEB: "02",
        MAR: "03",
        APR: "04",
        MAY: "05",
        JUN: "06",
        JUL: "07",
        AUG: "08",
        SEP: "09",
        OCT: "10",
        NOV: "11",
        DEC: "12"
    };

    match = text.match(/(?:EXP\s*)?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})\s+(\d{2,4})/);
    if (match) {
        const month = monthNames[match[1].slice(0, 3)];
        const day = match[2];
        let year = match[3];

        if (year.length === 2) year = "20" + year;
        return toIsoDate(year, month, day);
    }

    match = text.match(/(?:EXP\s*)?(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{2,4})/);
    if (match) {
        const day = match[1];
        const month = monthNames[match[2].slice(0, 3)];
        let year = match[3];

        if (year.length === 2) year = "20" + year;
        return toIsoDate(year, month, day);
    }

    match = text.match(/(?:EXP\s*)?(\d{1,2})[\/\-](\d{2})/);
    if (match) {
        const month = match[1];
        const yearTwoDigits = match[2];
        const inferredYear = "20" + yearTwoDigits;
        const inferredDay = "01";
        return toIsoDate(inferredYear, month, inferredDay);
    }

    return null;
}

function toIsoDate(year, month, day) {
    const y = String(year).padStart(4, "0");
    const m = String(month).padStart(2, "0");
    const d = String(day).padStart(2, "0");

    if (!isValidDateParts(y, m, d)) {
        return null;
    }

    return `${y}-${m}-${d}`;
}

function isValidDateParts(year, month, day) {
    const y = Number(year);
    const m = Number(month);
    const d = Number(day);

    if (Number.isNaN(y) || Number.isNaN(m) || Number.isNaN(d)) return false;
    if (m < 1 || m > 12) return false;
    if (d < 1 || d > 31) return false;
    if (y < 2020 || y > 2100) return false;

    const date = new Date(`${year}-${month}-${day}T00:00:00`);
    return (
        !Number.isNaN(date.getTime()) &&
        date.getFullYear() === y &&
        date.getMonth() + 1 === m &&
        date.getDate() === d
    );
}

function formatForDisplay(isoDate) {
    const [year, month, day] = isoDate.split("-");
    return `${month}/${day}/${year}`;
}

document.addEventListener("DOMContentLoaded", () => {
    toggleCustomCategory();
});