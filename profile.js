const STORAGE_KEY = "ecare_user_profile";

const form = document.getElementById("profileForm");
const formMsg = document.getElementById("formMsg");

const fields = {
  name: document.getElementById("name"),
  phone: document.getElementById("phone"),
  gender: document.getElementById("gender"),
  age: document.getElementById("age"),
  emergencyName: document.getElementById("emergencyName"),
  emergencyPhone: document.getElementById("emergencyPhone"),
  relationship: document.getElementById("relationship"),
  address: document.getElementById("address"),
  note: document.getElementById("note"),
};

function showMsg(text, isError = true) {
  formMsg.textContent = text;
  formMsg.style.color = isError ? "#B84B3D" : "#3A2A1D";
}

function loadExistingProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;

    const profile = JSON.parse(raw);

    fields.name.value = profile.name || "";
    fields.phone.value = profile.phone || "";
    fields.gender.value = profile.gender || "";
    fields.age.value = profile.age || "";
    fields.emergencyName.value = profile.emergencyName || "";
    fields.emergencyPhone.value = profile.emergencyPhone || "";
    fields.relationship.value = profile.relationship || "";
    fields.address.value = profile.address || "";
    fields.note.value = profile.note || "";
  } catch (err) {
    console.error("載入使用者資料失敗：", err);
  }
}

function isValidPhone(phone) {
  return /^[0-9+\-()#\s]{8,20}$/.test(phone);
}

if (form) {
  form.addEventListener("submit", (e) => {
    e.preventDefault();

    const profile = {
      name: fields.name.value.trim(),
      phone: fields.phone.value.trim(),
      gender: fields.gender.value.trim(),
      age: fields.age.value.trim(),
      emergencyName: fields.emergencyName.value.trim(),
      emergencyPhone: fields.emergencyPhone.value.trim(),
      relationship: fields.relationship.value.trim(),
      address: fields.address.value.trim(),
      note: fields.note.value.trim(),
      updatedAt: new Date().toISOString(),
    };

    if (!profile.name) {
      showMsg("請先填寫姓名喔～");
      fields.name.focus();
      return;
    }

    if (!profile.phone) {
      showMsg("請先填寫電話喔～");
      fields.phone.focus();
      return;
    }

    if (!isValidPhone(profile.phone)) {
      showMsg("電話格式看起來不太對，請再確認一下 📞");
      fields.phone.focus();
      return;
    }

    if (profile.emergencyPhone && !isValidPhone(profile.emergencyPhone)) {
      showMsg("緊急聯絡人電話格式不正確，請再確認一下 📞");
      fields.emergencyPhone.focus();
      return;
    }

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
      showMsg("資料已儲存，正在進入系統…", false);

      setTimeout(() => {
        window.location.href = "user.html";
      }, 500);
    } catch (err) {
      console.error(err);
      showMsg("儲存失敗，請再試一次。");
    }
  });
}

loadExistingProfile();