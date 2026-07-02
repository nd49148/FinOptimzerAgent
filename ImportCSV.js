/**
 * Firestore Import Script for Monthly Budget CSV (Wide → Long Format)
 * ---------------------------------------------------------------
 * Converts your CSV (categories as rows, months as columns)
 * into normalized monthly records and imports them into Firestore.
 */

const { initializeApp, cert } = require("firebase-admin/app");
const { getFirestore } = require("firebase-admin/firestore");
const fs = require("fs");
const csv = require("csv-parser");

// TODO: Replace with your Firebase service account JSON file
const app = initializeApp({
  credential: cert(require("./serviceAccountKey.json"))
});

const db = getFirestore(app);

// Month mapping based on your CSV
const MONTHS = [
  "January", "Feburary", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

// Utility: convert "$1,682.56" or "($21.90)" → number
function parseAmount(value) {
  if (!value || value.trim() === "" || value.includes("$-")) return null;

  let cleaned = value.replace(/[$,]/g, "").trim();

  // Handle negative values in parentheses
  if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
    cleaned = "-" + cleaned.slice(1, -1);
  }

  const num = parseFloat(cleaned);
  return isNaN(num) ? null : num;
}

// Determine type (Incoming vs Outgoing)
function detectType(category) {
  if (category.toLowerCase().includes("income")) return "Incoming";
  if (category.toLowerCase().includes("outgoing")) return null; // skip header
  if (category.toLowerCase().includes("savings")) return null; // skip derived
  return "Outgoing";
}

// Main import function
async function importCSV() {
  const results = [];

  fs.createReadStream("MonthlyExpSheet.csv")
    .pipe(csv())
    .on("data", (row) => results.push(row))
    .on("end", async () => {
      console.log("CSV loaded. Normalizing…");

      const batch = db.batch();
      const userId = "user-1"; // You can change this

      for (const row of results) {
        const category = row["Incoming"] || row["Outgoing"] || row["Category"] || row[""];
        const frequency = row["Frequencey"] || row["Frequency"] || "";

        if (!category || category.trim() === "") continue;

        const type = detectType(category);
        if (!type) continue; // skip headers & derived rows

        // Loop through each month column
        MONTHS.forEach((month) => {
          const rawAmount = row[month];
          const amount = parseAmount(rawAmount);

          if (amount === null) return; // skip empty or invalid cells

          const record = {
            user_id: userId,
            year: 2024, // You can change this
            month,
            date: `${2024}-${String(MONTHS.indexOf(month) + 1).padStart(2, "0")}-01`,
            category: category.trim(),
            type,
            frequency: frequency.trim(),
            amount,
            raw_amount: rawAmount,
            notes: rawAmount.includes("(") ? "Negative value detected" : ""
          };

          const docRef = db.collection("monthly_records").doc();
          batch.set(docRef, record);
        });
      }

      await batch.commit();
      console.log("Firestore import complete!");
    });
}

importCSV();
