// The Clinic: booking UI. Vanilla JS, no build step.
// Rule: every piece of API or user text goes in via textContent / createElement,
// never parsed as HTML markup, so hostile names or reasons render as plain text.
"use strict";

const TZ = "Africa/Nairobi";
const fmtDay = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" });
const fmtTime = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const fmtIsoDay = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const fmtWeekday = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short" });
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

// An icon from the sprite in index.html.
function icon(name) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

const initials = (name) => name.replace(/^Dr\.?\s+/i, "").split(/\s+/).filter(Boolean)
  .slice(0, 2).map((w) => w[0].toUpperCase()).join("");

// ---- dates (all in clinic time) -----------------------------------------------

const todayIso = () => fmtIsoDay.format(new Date());
function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
const daysBetween = (a, b) => Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000);
const dayLabel = (iso) => fmtDay.format(new Date(`${iso}T12:00:00+03:00`));
const timeOf = (isoDateTime) => fmtTime.format(new Date(isoDateTime));
const dayOf = (isoDateTime) => fmtIsoDay.format(new Date(isoDateTime));
const doctorOf = (id) => state.doctors.find((d) => d.id === id);
const doctorName = (id) => doctorOf(id)?.name ?? `Doctor ${id}`;
function relDay(iso) {
  const n = daysBetween(todayIso(), iso);
  return n === 0 ? "Today" : n === 1 ? "Tomorrow" : n > 1 ? `In ${n} days` : "";
}

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
      flash("Sign in again to continue.", "info", "Your session ended");
      state.returnTo = currentView();
      go("signin");
    }
    throw err;
  }
  return data;
}

// ---- feedback -----------------------------------------------------------------

const FLASH_ICONS = { ok: "check", error: "alert", info: "calendar" };

// kind: "ok" | "error" | "info"; title is optional.
function flash(message, kind = "ok", title = "") {
  const box = $("#flash");
  $("#flash-title").textContent = title;
  $("#flash-text").textContent = message;
  box.className = `banner is-${kind}`;
  $("use", box).setAttribute("href", `#i-${FLASH_ICONS[kind]}`);
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
  const name = me?.patient?.full_name ?? me?.email.split("@")[0] ?? "";
  $("#me-name").textContent = name;
  $("#me-initials").textContent = name ? initials(name) : "";
}

async function loadMe() {
  try { setMe(await api("GET", "/auth/me")); } catch { setMe(null); }
}

// ---- router -------------------------------------------------------------------

const TITLES = {
  book: "Book an appointment", appointments: "My appointments", schedule: "Day schedule",
  signin: "Sign in", signup: "Create an account", "check-email": "Check your email",
  verify: "Confirm your email", forgot: "Forgot your password", reset: "Choose a new password",
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
  document.body.dataset.page = name; // page-specific accents in CSS (the logo)
  window.scrollTo(0, 0); // a new view starts at its top, not where the last one was scrolled
  $("#main").focus({ preventScroll: true });

  if (name === "book") await showBook();
  if (name === "appointments") await showMine();
  if (name === "schedule") showScheduleForm();
  if (name === "verify") showVerify();
}

// ---- booking ------------------------------------------------------------------

function renderDoctors() {
  $("#doctor-count").textContent = `${state.doctors.length} doctors`;
  $("#doctors").replaceChildren(...state.doctors.map((d) =>
    el("label", { class: "doc" },
      el("input", {
        type: "radio", name: "doctor", value: d.id,
        checked: d.id === state.doctorId,
        disabled: Boolean(state.reschedule) && d.id !== state.doctorId,
        onchange: () => { state.doctorId = d.id; state.pick = null; loadStrip(); },
      }),
      el("span", { class: "avatar", "aria-hidden": "true", text: initials(d.name) }),
      el("span", { class: "doc-text" }, el("span", { class: "doc-name", text: d.name }), el("span", { class: "doc-spec", text: d.specialty })),
      el("span", { class: "doc-mark", "aria-hidden": "true" }, icon("check")),
    )));
}

function setDay(iso) {
  const min = todayIso();
  const max = addDays(min, MAX_DAYS);
  const day = iso < min ? min : iso > max ? max : iso;
  state.day = day;
  Object.assign($("#day"), { min, max, value: day });
  $("#prev-day").disabled = day <= min;
  $("#next-day").disabled = day >= max;
  $("#day-label").textContent = dayLabel(day);
  $("#day-sub").textContent = day === min ? "Today" : "";
  renderWeek(min, max);
  state.pick = null;
}

// Monday to Sunday around the chosen day; out-of-range days can't be picked.
function renderWeek(min, max) {
  const weekday = (new Date(`${state.day}T00:00:00Z`).getUTCDay() + 6) % 7; // Monday = 0
  const monday = addDays(state.day, -weekday);
  $("#week").replaceChildren(...Array.from({ length: 7 }, (_, i) => {
    const iso = addDays(monday, i);
    return el("button", {
      type: "button", "aria-pressed": String(iso === state.day), "aria-label": dayLabel(iso),
      disabled: iso < min || iso > max,
      onclick: () => { setDay(iso); loadStrip(); },
    },
    el("span", { class: "wd", text: fmtWeekday.format(new Date(`${iso}T12:00:00Z`)) }),
    el("span", { class: "dn", text: String(Number(iso.slice(8))) }));
  }));
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
    $("#reschedule-text").textContent =
      `Choosing a new time for your ${dayLabel(dayOf(a.start_at))} ${timeOf(a.start_at)} appointment with ${doctorName(a.doctor_id)}.`;
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

const gapRow = (from, to) =>
  el("li", { class: "gap" }, icon("cup"), el("span", { text: `Closed ${from}–${to}` }), el("span", { class: "tag", text: "Break" }));

async function loadStrip() {
  const strip = $("#strip");
  const count = $("#free-count");
  const hours = $("#day-hours");
  $("#confirm").hidden = true;
  count.hidden = true;
  hours.hidden = true;
  if (!state.doctorId) return;
  const doctor = doctorName(state.doctorId);
  $("#strip-sub").textContent = `${doctor} · ${dayLabel(state.day)}`;
  strip.setAttribute("aria-busy", "true");
  strip.replaceChildren(el("li", { class: "strip-empty", text: "Loading times…" }));
  let data;
  try {
    data = await api("GET", `/doctors/${state.doctorId}/availability?date=${state.day}`);
  } catch (err) {
    strip.replaceChildren(el("li", { class: "strip-empty error", text: err.message }));
    return;
  } finally {
    strip.removeAttribute("aria-busy");
  }

  if (!data.working_hours.length) {
    strip.replaceChildren(el("li", { class: "strip-empty", text: `${doctor} doesn't work on ${dayLabel(state.day)}. Try another day.` }));
    return;
  }
  const ranges = data.working_hours.map((r) => r.replace("-", "–"));
  $("span", hours).textContent = `${doctor} works ${ranges.join(" and ")} on this day.`;
  hours.hidden = false;
  count.textContent = `${data.slots.length} free`;
  count.hidden = false;

  const free = new Map(data.slots.map((s) => [timeOf(s.start), s]));
  const current = state.reschedule && dayOf(state.reschedule.start_at) === state.day && state.reschedule.doctor_id === state.doctorId
    ? timeOf(state.reschedule.start_at) : null;
  const verb = state.reschedule ? "Move to" : "Book";

  const parts = [];
  data.working_hours.forEach((range, i) => {
    if (i > 0) parts.push(gapRow(data.working_hours[i - 1].split("-")[1], range.split("-")[0]));
    for (const hhmm of windowSlots(range)) {
      const slot = free.get(hhmm);
      if (hhmm === current) {
        parts.push(el("li", { class: "slot is-current" }, el("p", { class: "slot-row" },
          el("time", { text: hhmm }), el("span", { class: "what", text: "Your current time" }), el("span", { class: "tag", text: "Current" }))));
      } else if (!slot) {
        // Not free: either booked, or already too close (bookings need an hour's notice).
        const late = new Date(`${state.day}T${hhmm}:00+03:00`) < Date.now() + 3600000;
        parts.push(el("li", { class: "slot is-off" }, el("p", { class: "slot-row" },
          el("time", { text: hhmm }), el("span", { class: "what", text: late ? "Too late to book" : "Not available" }), el("span", { class: "tag", text: late ? "Past" : "Taken" }))));
      } else {
        parts.push(el("li", { class: "slot" }, el("button", {
          type: "button", class: "slot-btn", "aria-pressed": "false",
          "aria-label": `${verb} ${hhmm} with ${doctor}`,
          onclick: (e) => choose(slot, e.currentTarget),
        }, el("time", { datetime: slot.start, text: hhmm }), el("span", { class: "what", text: `${verb} ${hhmm}` }), el("span", { class: "tag", text: "Free" }))));
      }
    }
  });
  if (!data.slots.length) {
    parts.push(el("li", { class: "strip-empty", text: "No free times left on this day. Try the next day." }));
  }
  strip.replaceChildren(...parts);
}

function choose(slot, button) {
  state.pick = slot;
  $$(".slot-btn", $("#strip")).forEach((b) => {
    const on = b === button;
    b.setAttribute("aria-pressed", String(on));
    $(".tag", b).textContent = on ? "Selected" : "Free";
  });
  const box = $("#confirm");
  const yes = $("#confirm-yes");
  const note = $("#confirm-text");
  $("#confirm-when").textContent = `${dayLabel(state.day)} at ${timeOf(slot.start)}`;
  $("#confirm-who").textContent = `with ${doctorName(state.doctorId)}`;
  note.hidden = true;
  yes.hidden = false;
  if (!state.me) {
    note.textContent = "Sign in or create an account to book it.";
    note.hidden = false;
    $("span", yes).textContent = "Sign in to book";
  } else if (state.me.role === "staff") {
    note.textContent = "Staff book for walk-in patients through the API (POST /appointments with patient_id).";
    note.hidden = false;
    yes.hidden = true;
  } else {
    $("span", yes).textContent = state.reschedule ? "Move appointment" : "Book appointment";
  }
  box.hidden = false;
  box.scrollIntoView({ block: "nearest" });
  (yes.hidden ? $("#confirm-no") : yes).focus({ preventScroll: true });
}

async function confirmPick() {
  if (!state.me) { state.returnTo = "book"; go("signin"); return; }
  const slot = state.pick;
  await busy($("#confirm-yes"), async () => {
    try {
      if (state.reschedule) {
        const moved = await api("PATCH", `/appointments/${state.reschedule.id}/reschedule`, { start_at: slot.start });
        state.reschedule = null;
        flash(`Now ${dayLabel(dayOf(moved.start_at))} at ${timeOf(moved.start_at)}. We've emailed you the new time.`, "ok", "Appointment moved");
        go("appointments");
        return;
      }
      const booked = await api("POST", "/appointments", { doctor_id: state.doctorId, start_at: slot.start });
      flash(`${dayLabel(dayOf(booked.start_at))} at ${timeOf(booked.start_at)} with ${doctorName(booked.doctor_id)}. A confirmation email is on its way.`, "ok", "Appointment booked");
      await loadStrip();
    } catch (err) {
      const title = err.code === "SLOT_TAKEN" ? "That time was just taken" : "Couldn't book that time";
      flash(err.message, "error", title);
      if (err.code === "SLOT_TAKEN" || err.code === "TOO_SOON") await loadStrip();
    }
  });
}

// ---- visit lists ----------------------------------------------------------------

// The inline "cancel with a reason" form shared by both lists.
function wireCancel(node, appt, onCancelled) {
  const form = $(".cancel-form", node);
  const open = $('[data-act="cancel"]', node);
  $(".cancel-title span", form).textContent = `Cancel ${dayLabel(dayOf(appt.start_at))} at ${timeOf(appt.start_at)}?`;
  open.addEventListener("click", () => { form.hidden = false; open.hidden = true; form.elements.reason.focus(); });
  $('[data-act="keep"]', node).addEventListener("click", () => { form.hidden = true; open.hidden = false; formError(form, null); open.focus(); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await busy($('button[type="submit"]', form), async () => {
      try {
        await api("PATCH", `/appointments/${appt.id}/cancel`, { reason: form.elements.reason.value });
        node.remove();
        onCancelled();
      } catch (err) { formError(form, err); }
    });
  });
}

function visitItem(appt) {
  const node = $("#visit-template").content.firstElementChild.cloneNode(true);
  const doctor = doctorOf(appt.doctor_id);
  const name = doctorName(appt.doctor_id);
  $(".avatar", node).textContent = initials(name);
  $(".rel", node).textContent = relDay(dayOf(appt.start_at));
  $(".spec", node).textContent = doctor?.specialty ?? "";
  $(".who", node).textContent = name;
  $(".date", node).textContent = dayLabel(dayOf(appt.start_at));
  $(".time", node).textContent = `${timeOf(appt.start_at)}–${timeOf(appt.end_at)} Nairobi time`;
  $('[data-act="reschedule"]', node).addEventListener("click", () => {
    state.reschedule = appt;
    state.doctorId = appt.doctor_id;
    setDay(dayOf(appt.start_at));
    go("book");
  });
  wireCancel(node, appt, () => {
    countMine();
    flash(`Your ${dayLabel(dayOf(appt.start_at))} ${timeOf(appt.start_at)} appointment is cancelled. The time is free for someone else now.`, "ok", "Appointment cancelled");
  });
  return node;
}

function countMine() {
  const n = $("#my-list").children.length;
  $("#my-count").textContent = n === 1 ? "1 visit" : `${n} visits`;
  $("#my-count").hidden = n === 0;
  $("#my-empty").hidden = n > 0;
}

async function showMine() {
  const list = $("#my-list");
  $("#my-empty").hidden = true;
  $("#my-count").hidden = true;
  list.replaceChildren(el("li", { class: "muted", text: "Loading…" }));
  try {
    if (!state.doctors.length) state.doctors = await api("GET", "/doctors");
    const page = await api("GET", `/patients/${state.me.patient.id}/appointments?limit=50`);
    list.replaceChildren(...page.items.map(visitItem));
    countMine();
  } catch (err) {
    list.replaceChildren(el("li", { class: "error", text: err.message }));
  }
}

async function showScheduleForm() {
  if (!state.doctors.length) state.doctors = await api("GET", "/doctors");
  const select = $("#schedule-doctor");
  if (!select.options.length) {
    select.replaceChildren(...state.doctors.map((d) => el("option", { value: d.id, text: `${d.name} · ${d.specialty}` })));
    $("#schedule-day").value = todayIso();
    $("#schedule-form").requestSubmit(); // open on today's schedule
  }
}

function rowItem(appt) {
  const node = $("#row-template").content.firstElementChild.cloneNode(true);
  $(".time", node).textContent = `${timeOf(appt.start_at)} – ${timeOf(appt.end_at)}`;
  $(".who", node).textContent = appt.patient_name;
  // Built here, not in the template: a link always has its href (ZAP 10109).
  $(".phone", node).replaceWith(el("a", { class: "phone", href: `tel:${appt.patient_phone}` },
    icon("phone"), el("span", { text: appt.patient_phone })));
  wireCancel(node, appt, () => {
    countSchedule();
    flash(`${appt.patient_name}'s ${timeOf(appt.start_at)} appointment is cancelled.`, "ok", "Appointment cancelled");
  });
  return node;
}

function countSchedule() {
  const n = $$("#schedule-list > .row").length;
  $("#schedule-count").textContent = String(n);
  $("#schedule-stats").hidden = false;
  $("#schedule-cols").hidden = n === 0;
  $("#schedule-empty").hidden = n > 0;
}

async function loadSchedule(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const list = $("#schedule-list");
  const error = $("#schedule-error");
  const doctorId = form.elements["schedule-doctor"].value;
  const day = form.elements["schedule-day"].value;
  error.hidden = true;
  await busy($('button[type="submit"]', form), async () => {
    try {
      const [items, avail] = await Promise.all([
        api("GET", `/doctors/${doctorId}/appointments?date=${day}`),
        api("GET", `/doctors/${doctorId}/availability?date=${day}`),
      ]);
      // Rows in time order, with the doctor's breaks between working windows.
      const rows = [];
      const windows = avail.working_hours;
      let next = 1;
      for (const a of items) {
        while (next < windows.length && timeOf(a.start_at) >= windows[next].split("-")[0]) {
          rows.push(gapRow(windows[next - 1].split("-")[1], windows[next].split("-")[0]));
          next += 1;
        }
        rows.push(rowItem(a));
      }
      list.replaceChildren(...(items.length ? rows : []));
      countSchedule();
    } catch (err) {
      list.replaceChildren();
      error.textContent = err.message;
      error.hidden = false;
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

function checkEmail(message, email) {
  $("#check-email-text").textContent = message;
  const to = $("#check-email-to");
  to.textContent = email ? `Sent to: ${email}` : "";
  to.hidden = !email;
  go("check-email");
}

// Opening the link only shows a button; confirming takes a deliberate click. So link
// scanners that run scripts, or a link someone else sends you, can't act for you.
function showVerify() {
  const hasToken = Boolean(pendingToken);
  const text = $("#verify-text");
  text.className = "notice";
  text.textContent = hasToken
    ? "Confirm this is your email address to finish creating your account."
    : "This page needs the link from your email.";
  $("#verify-confirm").hidden = !hasToken;
  $("#verify-next").hidden = hasToken;
}

async function confirmEmail(event) {
  await busy(event.currentTarget, async () => {
    const token = pendingToken;
    pendingToken = null;
    const text = $("#verify-text");
    try {
      text.textContent = (await api("POST", "/auth/verify", { token })).message;
      text.className = "notice is-ok";
    } catch (err) {
      text.textContent = err.message;
      text.className = "notice is-error";
    }
    $("#verify-confirm").hidden = true;
    $("#verify-next").hidden = false;
  });
}

function wireForms() {
  onSubmit("#signin-form", async (form) => {
    $("#resend-box").hidden = true;
    try {
      setMe(await api("POST", "/auth/login", values(form)));
    } catch (err) {
      if (err.code === "EMAIL_NOT_VERIFIED") { $("#resend-box").hidden = false; return; }
      throw err;
    }
    form.reset();
    flash("");
    const target = state.returnTo ?? home();
    state.returnTo = null;
    go(target);
  });
  $("#resend").addEventListener("click", async (event) => {
    const email = $("#signin-email").value;
    await busy(event.currentTarget, async () => {
      const r = await api("POST", "/auth/resend-verification", { email }).catch(() => null);
      checkEmail(r?.message ?? $("#check-email-text").textContent, email);
    });
  });
  // The server's wording says whether the emailed link is needed before signing in.
  onSubmit("#signup-form", async (form) => {
    const { email } = values(form);
    const r = await api("POST", "/auth/register", values(form));
    form.reset();
    checkEmail(r.message, email);
  });
  onSubmit("#forgot-form", async (form) => {
    const { email } = values(form);
    const r = await api("POST", "/auth/forgot-password", values(form));
    form.reset();
    checkEmail(r.message, email);
  });
  onSubmit("#reset-form", async (form) => {
    if (!pendingToken) throw new ApiError(0, "NO_TOKEN", "Open the reset link from your email again; it can only be used once.", {});
    const r = await api("POST", "/auth/reset-password", { token: pendingToken, password: form.elements.password.value });
    pendingToken = null;
    form.reset();
    flash(r.message, "ok", "Password saved");
    go("signin");
  });
  $("#signout").addEventListener("click", async () => {
    await api("POST", "/auth/logout").catch(() => {});
    setMe(null);
    state.reschedule = null;
    flash("You're signed out.", "info");
    go("signin");
  });
  $$(".reveal").forEach((button) => button.addEventListener("click", () => {
    const input = $("input", button.parentElement);
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));
  $("#flash-close").addEventListener("click", () => flash(""));
  $("#keep-time").addEventListener("click", () => { state.reschedule = null; go("appointments"); });
  $("#schedule-form").addEventListener("submit", loadSchedule);
  $("#verify-confirm").addEventListener("click", confirmEmail);
  $("#confirm-yes").addEventListener("click", confirmPick);
  $("#confirm-no").addEventListener("click", () => {
    $("#confirm").hidden = true;
    state.pick = null;
    $$(".slot-btn[aria-pressed='true']").forEach((b) => { b.setAttribute("aria-pressed", "false"); $(".tag", b).textContent = "Free"; });
  });
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
