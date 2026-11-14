// Vrai dans le build mobile (`vite build --mode mobile`) : application en lecture seule.
export const READONLY = import.meta.env.MODE === "mobile";
