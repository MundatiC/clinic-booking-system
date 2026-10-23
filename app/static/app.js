// The Clinic: booking UI. Vanilla JS, no build step.
// Rule: every piece of API or user text goes in via textContent / createElement,
// never parsed as HTML markup, so hostile names or reasons render as plain text.
"use strict";

const TZ = "Africa/Nairobi";
const fmtDay = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" });
const fmtTime = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const fmtIsoDay = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const MAX_DAYS = 90;

const state = {
  me: null,          // the signed-in account, or null
  doctors: [],
  doctorId: null,
  day: null,         // YYYY-MM-DD, clinic-local
  pick: null,        // the free slot chosen on the strip
  reschedule: null,  // the appointment being moved, if any
  returnTo: null,    // view to go back to after signing in
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false && value != null) node.setAttribute(key, String(value));
  }
  node.append(...children);
  return node;
}

// ---- dates (all in clinic time) -----------------------------------------------

const todayIso = () => fmtIsoDay.format(new Date());
function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
const dayLabel = (iso) => fmtDay.format(new Date(`${iso}T12:00:00+03:00`));
const timeOf = (isoDateTime) => fmtTime.format(new Date(isoDateTime));
const dayOf = (isoDateTime) => fmtIsoDay.format(new Date(isoDateTime));
const doctorName = (id) => state.doctors.find((d) => d.id === id)?.name ?? `Doctor ${id}`;

// ---- API ----------------------------------------------------------------------

class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    Object.assign(this, { status, code, details });
  }
}

async function api(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "NETWORK", "Can't reach the clinic right now. Check your connection and try again.", {});
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const e = data?.error ?? {};
    const err = new ApiError(res.status, e.code ?? `HTTP_${res.status}`, e.message ?? "Something went wrong. Please try again.", e.details ?? {});
    if (err.code === "NOT_AUTHENTICATED" && state.me) {
      setMe(null);
      flash("Your session ended. Sign in again to continue.", true);
      state.returnTo = currentView();
      go("signin");
    }
    throw err;
  }
  return data;
}

// ---- feedback -----------------------------------------------------------------

function flash(message, isError = false) {
  const box = $("#flash");
  box.textContent = message;
  box.classList.toggle("is-error", isError);
  box.hidden = !message;
  box.dataset.at = String(Date.now());
  if (message) box.scrollIntoView({ block: "nearest" }); // results land below the fold
}

function formError(form, err) {
  const box = $(".error", form);
  $$("[aria-invalid]", form).forEach((i) => i.removeAttribute("aria-invalid"));
  if (!err) { box.hidden = true; return; }
  let message = err.message;
  const fieldErrors = err.details?.errors;
  if (err.code === "VALIDATION_ERROR" && Array.isArray(fieldErrors) && fieldErrors.length) {
    const field = fieldErrors[0].loc?.at(-1);
    const input = field && form.elements.namedItem(field);
    const label = input && $(`label[for="${input.id}"]`)?.textContent;
    if (input) input.setAttribute("aria-invalid", "true");
    message = label ? `${label}: ${fieldErrors[0].msg}` : fieldErrors[0].msg;
  }
  box.textContent = message;
  box.hidden = false;
}

async function busy(button, task) {
  button.disabled = true;
  try { return await task(); } finally { button.disabled = false; }
}

// ---- account ------------------------------------------------------------------

function setMe(me) {
  state.me = me;
  const role = me?.role;
  $$("[data-when]").forEach((node) => {
    const when = node.dataset.when;
    node.hidden = !(
      (when === "anon" && !me) || (when === "user" && me) || (when === role)
    );
  });
}

async function loadMe() {
  try { setMe(await api("GET", "/auth/me")); } catch { setMe(null); }
}

// ---- router -------------------------------------------------------------------

const TITLES = {
  book: "Book an appointment", appointments: "My appointments", schedule: "Day schedule",
  signin: "Sign in", signup: "Create an account", "check-email": "Check your email",
  verify: "Confirm your email", forgot: "Reset your password", reset: "Choose a new password",
};

function parseHash() {
  const [name, query] = location.hash.replace(/^#\/?/, "").split("?");
  return { name: name || "book", params: new URLSearchParams(query ?? "") };
}
const currentView = () => parseHash().name;
const go = (name) => {
  if (location.hash === `#/${name}`) route(); // same hash fires no hashchange
  else location.hash = `#/${name}`;
};
const home = () => (state.me?.role === "staff" ? "schedule" : "book");
const ROLE_VIEWS = { appointments: "patient", schedule: "staff" };

// Email links carry tokens in the fragment (never sent to servers); read once, then
// wipe them from the address bar and history.
function takeToken(params, view) {
  const token = params.get("token");
  if (token) history.replaceState(null, "", `#/${view}`);
  return token;
}
let pendingToken = null;

async function route() {
  let { name, params } = parseHash();
  if (!TITLES[name]) name = "book";
  if (ROLE_VIEWS[name] && state.me?.role !== ROLE_VIEWS[name]) {
    // Signed in with the other role: their own home page, not a sign-in form again.
    if (state.me) name = home();
    else { state.returnTo = name; name = "signin"; }
  }
  if ((name === "verify" || name === "reset") && params.get("token")) pendingToken = takeToken(params, name);

  $$("[data-view]").forEach((s) => { s.hidden = s.dataset.view !== name; });
  $$("[data-nav]").forEach((a) => {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = `${TITLES[name]}: The Clinic`;
  $("#main").focus({ preventScroll: true });

  if (name === "book") await showBook();
  if (name === "appointments") await showMine();
  if (name === "schedule") showScheduleForm();
  if (name === "verify") showVerify();
}

// ---- booking ------------------------------------------------------------------

function renderDoctors() {
  const box = $("#doctors");
  box.replaceChildren(...state.doctors.map((d) =>
    el("label", { class: "doctor" },
      el("input", {
        type: "radio", name: "doctor", value: d.id,
        checked: d.id === state.doctorId,
        disabled: Boolean(state.reschedule) && d.id !== state.doctorId,
        onchange: () => { state.doctorId = d.id; state.pick = null; loadStrip(); },
      }),
      el("div", {}, el("strong", { text: d.name }), el("span", { text: d.specialty })),
    )));
}

function setDay(iso) {
  const min = todayIso();
  const max = addDays(min, MAX_DAYS);
  const day = iso < min ? min : iso > max ? max : iso;
  state.day = day;
  const input = $("#day");
  Object.assign(input, { min, max, value: day });
  $("#prev-day").disabled = day <= min;
  $("#next-day").disabled = day >= max;
  $("#day-label").textContent = dayLabel(day);
  state.pick = null;
}

async function showBook() {
  if (!state.doctors.length) {
    try {
      state.doctors = await api("GET", "/doctors");
    } catch (err) {
      $("#doctors").replaceChildren(el("p", { class: "error", text: err.message }));
      return;
    }
  }
  state.doctorId ??= state.doctors[0]?.id ?? null;
  if (!state.day) setDay(todayIso());
  renderDoctors();
  const note = $("#reschedule-note");
  note.hidden = !state.reschedule;
  if (state.reschedule) {
    const a = state.reschedule;
    note.replaceChildren(
      `Choosing a new time for your appointment on ${dayLabel(dayOf(a.start_at))} at ${timeOf(a.start_at)}. `,
      el("button", { type: "button", class: "link", text: "Keep the current time", onclick: () => { state.reschedule = null; go("appointments"); } }),
    );
  }
  await loadStrip();
}

function windowSlots(range) {
  const [start, end] = range.split("-").map((t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; });
  const out = [];
  for (let t = Math.ceil(start / 30) * 30; t + 30 <= end; t += 30) {
    out.push(`${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  }
  return out;
}

async function loadStrip() {
  const strip = $("#strip");
  $("#confirm").hidden = true;
  if (!state.doctorId) return;
  const doctor = doctorName(state.doctorId);
  $("#strip-title").textContent = `${doctor}, ${dayLabel(state.day)}`;
  strip.setAttribute("aria-busy", "true");
  strip.replaceChildren(el("p", { class: "strip-empty", text: "Loading times…" }));
  let data;
  try {
    data = await api("GET", `/doctors/${state.doctorId}/availability?date=${state.day}`);
  } catch (err) {
    strip.replaceChildren(el("p", { class: "strip-empty error", text: err.message }));
    return;
  } finally {
    strip.removeAttribute("aria-busy");
  }

  if (!data.working_hours.length) {
    strip.replaceChildren(el("p", { class: "strip-empty", text: `${doctor} doesn't work on ${dayLabel(state.day)}. Try another day.` }));
    return;
  }
  const free = new Map(data.slots.map((s) => [timeOf(s.start), s]));
  const current = state.reschedule && dayOf(state.reschedule.start_at) === state.day && state.reschedule.doctor_id === state.doctorId
    ? timeOf(state.reschedule.start_at) : null;

  const parts = [];
  data.working_hours.forEach((range, i) => {
    if (i > 0) {
      const closedFrom = data.working_hours[i - 1].split("-")[1];
      parts.push(el("p", { class: "gap", text: `Closed ${closedFrom}–${range.split("-")[0]}` }));
    }
    parts.push(el("ol", { class: "window", "aria-label": `Times from ${range.replace("-", " to ")}` },
      ...windowSlots(range).map((hhmm) => {
        const slot = free.get(hhmm);
        if (hhmm === current) {
          return el("li", { class: "slot is-current" }, el("time", { text: hhmm }), el("span", { text: "Your current time" }));
        }
        if (!slot) {
          return el("li", { class: "slot is-off" }, el("time", { text: hhmm }), el("span", { text: "Not available" }));
        }
        return el("li", { class: "slot is-free" },
          el("time", { datetime: slot.start, text: hhmm }),
          el("button", {
            type: "button", class: "ghost", text: state.reschedule ? `Move to ${hhmm}` : `Book ${hhmm}`,
            "aria-label": `${state.reschedule ? "Move to" : "Book"} ${hhmm} with ${doctor}`,
            onclick: () => choose(slot),
          }));
      })));
  });
  if (!data.slots.length) {
    parts.push(el("p", { class: "strip-empty", text: "No free times left on this day. Try the next day." }));
  }
  strip.replaceChildren(...parts);
}

function choose(slot) {
  state.pick = slot;
  const box = $("#confirm");
  const yes = $("#confirm-yes");
  const what = `${dayLabel(state.day)} at ${timeOf(slot.start)} with ${doctorName(state.doctorId)}.`;
  if (!state.me) {
    $("#confirm-text").textContent = `${what} Sign in or create an account to book it.`;
    yes.textContent = "Sign in to book";
  } else if (state.me.role === "staff") {
    $("#confirm-text").textContent = `${what} Staff book for walk-in patients through the API (POST /appointments with patient_id).`;
    yes.hidden = true;
  } else {
    $("#confirm-text").textContent = state.reschedule ? `Move your appointment to ${what}` : `Book ${what}`;
    yes.textContent = state.reschedule ? "Move appointment" : "Book appointment";
    yes.hidden = false;
  }
  box.hidden = false;
  yes.focus();
}

async function confirmPick() {
  if (!state.me) { state.returnTo = "book"; go("signin"); return; }
  const slot = state.pick;
  await busy($("#confirm-yes"), async () => {
    try {
      if (state.reschedule) {
        const moved = await api("PATCH", `/appointments/${state.reschedule.id}/reschedule`, { start_at: slot.start });
        state.reschedule = null;
        flash(`Moved: ${dayLabel(dayOf(moved.start_at))} at ${timeOf(moved.start_at)}. We've emailed you the new time.`);
        go("appointments");
        return;
      }
      const booked = await api("POST", "/appointments", { doctor_id: state.doctorId, start_at: slot.start });
      flash(`Booked: ${dayLabel(dayOf(booked.start_at))} at ${timeOf(booked.start_at)} with ${doctorName(booked.doctor_id)}. A confirmation email is on its way.`);
      await loadStrip();
    } catch (err) {
      flash(err.message, true);
      if (err.code === "SLOT_TAKEN" || err.code === "TOO_SOON") await loadStrip();
    }
  });
}

// ---- visit lists ----------------------------------------------------------------

function visitItem(appt, { who, canMove }) {
  const node = $("#visit-template").content.firstElementChild.cloneNode(true);
  $(".date", node).textContent = dayLabel(dayOf(appt.start_at));
  $(".time", node).textContent = `${timeOf(appt.start_at)}–${timeOf(appt.end_at)}`;
  $(".who", node).textContent = who;
  const form = $(".cancel-form", node);
  const move = $('[data-act="reschedule"]', node);
  move.hidden = !canMove;
  move.addEventListener("click", () => {
    state.reschedule = appt;
    state.doctorId = appt.doctor_id;
    setDay(dayOf(appt.start_at));
    go("book");
  });
  $('[data-act="cancel"]', node).addEventListener("click", () => { form.hidden = false; form.elements.reason.focus(); });
  $('[data-act="keep"]', node).addEventListener("click", () => { form.hidden = true; formError(form, null); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await busy($('button[type="submit"]', form), async () => {
      try {
        await api("PATCH", `/appointments/${appt.id}/cancel`, { reason: form.elements.reason.value });
        const list = node.parentElement;
        node.remove();
        list.nextElementSibling.hidden = list.children.length > 0; // the list's "nothing here" note
        flash(`Cancelled your ${dayLabel(dayOf(appt.start_at))} ${timeOf(appt.start_at)} appointment. The time is free for someone else now.`);
      } catch (err) { formError(form, err); }
    });
  });
  return node;
}

async function showMine() {
  const list = $("#my-list");
  list.replaceChildren(el("li", { class: "muted", text: "Loading…" }));
  try {
    if (!state.doctors.length) state.doctors = await api("GET", "/doctors");
    const page = await api("GET", `/patients/${state.me.patient.id}/appointments?limit=50`);
    list.replaceChildren(...page.items.map((a) => visitItem(a, { who: doctorName(a.doctor_id), canMove: true })));
    $("#my-empty").hidden = page.items.length > 0;
  } catch (err) {
    list.replaceChildren(el("li", { class: "error", text: err.message }));
  }
}

async function showScheduleForm() {
  if (!state.doctors.length) state.doctors = await api("GET", "/doctors");
  const select = $("#schedule-doctor");
  if (!select.options.length) {
    select.replaceChildren(...state.doctors.map((d) => el("option", { value: d.id, text: `${d.name}, ${d.specialty}` })));
    $("#schedule-day").value = todayIso();
  }
}

async function loadSchedule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const list = $("#schedule-list");
  await busy($('button[type="submit"]', form), async () => {
    try {
      const items = await api("GET", `/doctors/${form.elements["schedule-doctor"].value}/appointments?date=${form.elements["schedule-day"].value}`);
      list.replaceChildren(...items.map((a) => visitItem(a, { who: a.patient_name, canMove: false })));
      $("#schedule-empty").hidden = items.length > 0;
    } catch (err) {
      list.replaceChildren(el("li", { class: "error", text: err.message }));
    }
  });
}

// ---- auth forms -----------------------------------------------------------------

function onSubmit(id, handler) {
  const form = $(id);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formError(form, null);
    await busy($('button[type="submit"]', form), async () => {
      try { await handler(form); } catch (err) { formError(form, err); throw err; }
    }).catch(() => {});
  });
}

const values = (form) => Object.fromEntries(new FormData(form));

// Opening the link only shows a button; confirming takes a deliberate click. So link
// scanners that run scripts, or a link someone else sends you, can't act for you.
function showVerify() {
  const hasToken = Boolean(pendingToken);
  $("#verify-text").textContent = hasToken
    ? "Confirm this is your email address to finish creating your account."
    : "This page needs the link from your email.";
  $("#verify-confirm").hidden = !hasToken;
  $("#verify-next").hidden = hasToken;
}

async function confirmEmail(event) {
  await busy(event.currentTarget, async () => {
    const token = pendingToken;
    pendingToken = null;
    try {
      $("#verify-text").textContent = (await api("POST", "/auth/verify", { token })).message;
    } catch (err) {
      $("#verify-text").textContent = err.message;
    }
    $("#verify-confirm").hidden = true;
    $("#verify-next").hidden = false;
  });
}

function wireForms() {
  onSubmit("#signin-form", async (form) => {
    $("#resend").hidden = true;
    try {
      setMe(await api("POST", "/auth/login", values(form)));
    } catch (err) {
      if (err.code === "EMAIL_NOT_VERIFIED") $("#resend").hidden = false;
      throw err;
    }
    form.reset();
    flash("");
    const target = state.returnTo ?? home();
    state.returnTo = null;
    go(target);
  });
  $("#resend").addEventListener("click", async (event) => {
    await busy(event.currentTarget, async () => {
      await api("POST", "/auth/resend-verification", { email: $("#signin-email").value }).catch(() => {});
      go("check-email");
    });
  });
  // The server's wording says whether the emailed link is needed before signing in.
  onSubmit("#signup-form", async (form) => {
    $("#check-email-text").textContent = (await api("POST", "/auth/register", values(form))).message;
    form.reset();
    go("check-email");
  });
  onSubmit("#forgot-form", async (form) => {
    $("#check-email-text").textContent = (await api("POST", "/auth/forgot-password", values(form))).message;
    form.reset();
    go("check-email");
  });
  onSubmit("#reset-form", async (form) => {
    if (!pendingToken) throw new ApiError(0, "NO_TOKEN", "Open the reset link from your email again; it can only be used once.", {});
    const r = await api("POST", "/auth/reset-password", { token: pendingToken, password: form.elements.password.value });
    pendingToken = null;
    form.reset();
    flash(r.message);
    go("signin");
  });
  $("#signout").addEventListener("click", async () => {
    await api("POST", "/auth/logout").catch(() => {});
    setMe(null);
    state.reschedule = null;
    flash("You're signed out.");
    go("signin");
  });
  $("#schedule-form").addEventListener("submit", loadSchedule);
  $("#verify-confirm").addEventListener("click", confirmEmail);
  $("#confirm-yes").addEventListener("click", confirmPick);
  $("#confirm-no").addEventListener("click", () => { $("#confirm").hidden = true; state.pick = null; });
  $("#day").addEventListener("change", (e) => { if (e.target.value) { setDay(e.target.value); loadStrip(); } });
  $("#prev-day").addEventListener("click", () => { setDay(addDays(state.day, -1)); loadStrip(); });
  $("#next-day").addEventListener("click", () => { setDay(addDays(state.day, 1)); loadStrip(); });
}

// ---- start ----------------------------------------------------------------------

window.addEventListener("hashchange", () => {
  // A message belongs to the screen it was shown on; keep one set just before navigating.
  if (Date.now() - Number($("#flash").dataset.at ?? 0) > 1000) flash("");
  route();
});

(async () => {
  wireForms();
  await loadMe();
  await route();
})();
