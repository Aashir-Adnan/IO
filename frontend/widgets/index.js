import { mountTodo } from "./todo.js";
import { mountWeather } from "./weather.js";
import { mountTimezones } from "./timezones.js";
import { mountAlerts } from "./alerts.js";

// The premade widgets. `action` adds a small button to the card header.
export const WIDGETS = {
  todo: {
    title: "To-do", mount: mountTodo,
    action: {
      icon: "arrowSquareOut", title: "Open in a small window",
      run: () => { try { window.pywebview.api.open_tasks(); } catch { /* not in the desktop shell */ } },
    },
  },
  weather: { title: "Weather", mount: mountWeather },
  timezones: { title: "Time zones", mount: mountTimezones },
  alerts: { title: "Important", mount: mountAlerts },
};

export const TYPES = Object.keys(WIDGETS);

let n = 0;
export const newId = (type) => `${type}-${Date.now().toString(36)}${(n++).toString(36)}`;

// All four come premade: to-do 2×2, Important 2×1 beside it, weather and clocks below it.
export const defaultLayout = () => [
  { id: newId("todo"), type: "todo", size: "L", col: 0, row: 0 },
  { id: newId("alerts"), type: "alerts", size: "M", col: 2, row: 0 },
  { id: newId("weather"), type: "weather", size: "S", col: 2, row: 1 },
  { id: newId("timezones"), type: "timezones", size: "S", col: 3, row: 1 },
];
