// The ONLY place that changes when the API moves to a server (e.g. Oracle).
//   Offline .exe : apiBase = ""                      (same origin as Flask)
//   Online       : apiBase = "https://your-server"   (frontend hosted separately)
window.APP_CONFIG = {
  apiBase: "",
  businessName: "Agni Gas Agency",
  currency: "Rs",
  locale: "en-IN",   // 1,15,250 grouping
};
