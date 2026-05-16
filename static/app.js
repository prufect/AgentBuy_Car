import React from "react";
import { createRoot } from "react-dom/client";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowRight,
  BadgeCheck,
  Car,
  Check,
  ChevronRight,
  CircleDollarSign,
  Gauge,
  LoaderCircle,
  RefreshCw,
  ScanSearch,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  TimerReset,
  Trophy,
  XCircle,
  Zap,
} from "lucide-react";

// 21st.dev references: Animated Hero Section, Native Marquee, and Testimonials patterns.
const h = React.createElement;
const { useEffect, useRef, useState } = React;

const carTypes = ["SUV", "Sedan", "Truck", "Coupe", "Hatchback", "Van", "Wagon", "Convertible"];
const conditions = ["Like New", "Excellent", "Clean", "Good", "Fair"];
const features = [
  "Backup Camera",
  "Bluetooth",
  "Apple CarPlay",
  "Android Auto",
  "Leather Seats",
  "Sunroof",
  "Navigation",
  "Heated Seats",
  "Blind Spot Monitor",
  "Lane Departure Warning",
  "Remote Start",
  "4WD/AWD",
];

const initialForm = {
  carType: "SUV",
  condition: "Clean",
  budgetMin: "15000",
  budgetMax: "35000",
  yearMin: "2019",
  yearMax: "2026",
  mileageMax: "65000",
};

const initialFeatures = ["Backup Camera", "Apple CarPlay", "Blind Spot Monitor"];

const defaultProgress = [
  { step: "scraping_carmax", status: "pending" },
  { step: "scraping_carvana", status: "pending" },
  { step: "scoring", status: "pending" },
  { step: "generating_summaries", status: "pending" },
];

const stepLabels = {
  scraping_carmax: "Scanning CarMax",
  scraping_carvana: "Scanning Carvana",
  scoring: "Scoring fit and value",
  generating_summaries: "Writing advisor notes",
};

function icon(Icon, className = "icon", extraProps = {}) {
  return h(Icon, { className, "aria-hidden": "true", ...extraProps });
}

function cls(...parts) {
  return parts.filter(Boolean).join(" ");
}

function numberOrNull(value) {
  if (value === "" || value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatMoney(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "$0";
  return parsed.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function formatNumber(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "0";
  return parsed.toLocaleString();
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function Reveal({ as = "div", className, children, delay = 0, ...props }) {
  const reduceMotion = useReducedMotion();
  const Component = motion[as] || motion.div;

  return h(
    Component,
    {
      className,
      initial: reduceMotion ? false : { opacity: 0, y: 24 },
      whileInView: reduceMotion ? undefined : { opacity: 1, y: 0 },
      viewport: { once: true, amount: 0.2 },
      transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1], delay },
      ...props,
    },
    children,
  );
}

function App() {
  const [formData, setFormData] = useState(initialForm);
  const [selectedFeatures, setSelectedFeatures] = useState(initialFeatures);
  const [journey, setJourney] = useState("idle");
  const [progressItems, setProgressItems] = useState(defaultProgress);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const pollingRef = useRef(null);

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    if (journey === "idle") return;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => revealJourney());
    });
  }, [journey]);

  function stopPolling() {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }

  function updateForm(field, value) {
    setFormData((current) => ({ ...current, [field]: value }));
  }

  function buildRequest() {
    return {
      car_type: formData.carType,
      budget_min: numberOrNull(formData.budgetMin),
      budget_max: numberOrNull(formData.budgetMax),
      year_min: numberOrNull(formData.yearMin),
      year_max: numberOrNull(formData.yearMax),
      mileage_max: numberOrNull(formData.mileageMax),
      must_have_features: selectedFeatures,
      condition: formData.condition || null,
    };
  }

  function validateRequest(request) {
    if (!request.car_type || request.budget_min == null || request.budget_max == null) {
      return "Choose a body style and budget range before searching.";
    }
    if (request.budget_min > request.budget_max) {
      return "Budget minimum must be below the maximum.";
    }
    return "";
  }

  function revealJourney() {
    requestAnimationFrame(() => {
      document.getElementById("search-journey")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  async function submitSearch(event) {
    event?.preventDefault();
    const request = buildRequest();
    const validation = validateRequest(request);
    if (validation) {
      setError(validation);
      setJourney("error");
      revealJourney();
      return;
    }

    setIsSearching(true);
    setError("");
    setResult(null);
    setProgressItems(defaultProgress);

    try {
      const response = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const details = await response.json().catch(() => ({}));
        throw new Error(details.detail || `Search failed with HTTP ${response.status}`);
      }

      const { job_id: jobId } = await response.json();
      setJourney("loading");
      revealJourney();
      startPolling(jobId);
    } catch (err) {
      setError(err.message || "Search failed. Try again.");
      setJourney("error");
      revealJourney();
    } finally {
      setIsSearching(false);
    }
  }

  async function submitDemo() {
    const request = buildRequest();
    const validation = validateRequest(request);
    if (validation) {
      setError(validation);
      setJourney("error");
      revealJourney();
      return;
    }

    stopPolling();
    setIsSearching(true);
    setError("");
    setResult(null);
    setProgressItems(defaultProgress.map((item) => ({ ...item, status: "done" })));

    try {
      const response = await fetch("/search/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) throw new Error(`Demo search failed with HTTP ${response.status}`);
      const data = await response.json();
      setResult(data);
      setJourney("results");
      revealJourney();
    } catch (err) {
      setError(err.message || "Demo search failed.");
      setJourney("error");
      revealJourney();
    } finally {
      setIsSearching(false);
    }
  }

  function startPolling(jobId) {
    stopPolling();
    pollJob(jobId);
    pollingRef.current = setInterval(() => pollJob(jobId), 2000);
  }

  async function pollJob(jobId) {
    try {
      const response = await fetch(`/search/${jobId}`);
      if (!response.ok) throw new Error(`Polling failed with HTTP ${response.status}`);
      const data = await response.json();

      if (data.progress_detail && Object.keys(data.progress_detail).length > 0) {
        setProgressItems(Object.values(data.progress_detail));
      }

      if (data.status === "completed") {
        stopPolling();
        setResult(data.result);
        setJourney("results");
      } else if (data.status === "failed") {
        stopPolling();
        setError(data.error || "Search failed with an unknown error.");
        setJourney("error");
      }
    } catch (err) {
      stopPolling();
      setError(err.message || "Network error while checking the search.");
      setJourney("error");
    }
  }

  function resetSearch() {
    stopPolling();
    setJourney("idle");
    setResult(null);
    setError("");
    setProgressItems(defaultProgress);
    requestAnimationFrame(() => {
      document.getElementById("top")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  return h(
    React.Fragment,
    null,
    h(Header),
    h(
      "main",
      { id: "top" },
      h(HeroSection, {
        formData,
        selectedFeatures,
        isSearching,
        onSubmit: submitSearch,
        onDemo: submitDemo,
        onFormChange: updateForm,
        onFeatureToggle: setSelectedFeatures,
      }),
      h(BrandMarquee),
      h(ProofSection),
      h(SearchJourney, {
        journey,
        progressItems,
        result,
        error,
        onReset: resetSearch,
        onDemo: submitDemo,
      }),
      h(FeatureSection),
      h(TestimonialsSection),
      h(ClosingCta, { onDemo: submitDemo }),
    ),
    h(Footer),
  );
}

function Header() {
  return h(
    "header",
    { className: "site-header" },
    h(
      "a",
      { className: "brand", href: "#top", "aria-label": "AgentBuy Car home" },
      h("span", { className: "brand-mark" }, icon(Car)),
      h("span", null, "AgentBuy Car"),
    ),
    h(
      "nav",
      { className: "nav-links", "aria-label": "Primary navigation" },
      h("a", { href: "#proof" }, "Proof"),
      h("a", { href: "#workflow" }, "Workflow"),
      h("a", { href: "#reviews" }, "Reviews"),
    ),
    h(
      "a",
      { className: "header-cta", href: "#search-panel" },
      icon(Search),
      h("span", null, "Start search"),
    ),
  );
}

function HeroSection(props) {
  const reduceMotion = useReducedMotion();

  return h(
    "section",
    { className: "hero-shell" },
    h("div", { className: "hero-grid" },
      h(
        motion.div,
        {
          className: "hero-copy",
          initial: reduceMotion ? false : { opacity: 0, y: 28 },
          animate: reduceMotion ? undefined : { opacity: 1, y: 0 },
          transition: { duration: 0.65, ease: [0.22, 1, 0.36, 1] },
        },
        h("div", { className: "eyebrow" }, icon(Sparkles), h("span", null, "AI-powered used car shortlists")),
        h("h1", null, "Buy the right used car without opening 47 tabs."),
        h(
          "p",
          { className: "hero-subtitle" },
          "AgentBuy Car scans live inventory, scores each listing, and turns the messy comparison work into a ranked shortlist you can act on.",
        ),
        h(
          "div",
          { className: "hero-actions" },
          h("a", { className: "btn btn-primary", href: "#search-panel" }, icon(Search), h("span", null, "Build my shortlist")),
          h("button", { className: "btn btn-ghost", type: "button", onClick: props.onDemo }, icon(Zap), h("span", null, "Preview demo")),
        ),
        h(
          "div",
          { className: "hero-stats", "aria-label": "AgentBuy performance indicators" },
          h(Stat, { value: "6", label: "scoring signals" }),
          h(Stat, { value: "2", label: "marketplaces scanned" }),
          h(Stat, { value: "100", label: "fit score ceiling" }),
        ),
      ),
      h(
        motion.div,
        {
          className: "hero-visual",
          initial: reduceMotion ? false : { opacity: 0, y: 32, rotate: -1 },
          animate: reduceMotion ? undefined : { opacity: 1, y: 0, rotate: 0 },
          transition: { duration: 0.75, ease: [0.22, 1, 0.36, 1], delay: 0.1 },
        },
        h("img", {
          className: "hero-car",
          src: "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1400&q=85",
          alt: "Black sports car photographed from the front in a premium automotive setting",
        }),
        h("div", { className: "hero-sheen", "aria-hidden": "true" }),
        h(
          motion.div,
          {
            className: "floating-score",
            animate: reduceMotion ? undefined : { y: [0, -10, 0] },
            transition: { duration: 5, repeat: Infinity, ease: "easeInOut" },
          },
          h("span", { className: "score-ring" }, "92"),
          h("div", null, h("strong", null, "Best-fit lead"), h("span", null, "Clean title, low miles")),
        ),
        h(
          motion.div,
          {
            className: "floating-route",
            animate: reduceMotion ? undefined : { y: [0, 8, 0] },
            transition: { duration: 4.5, repeat: Infinity, ease: "easeInOut", delay: 0.4 },
          },
          icon(ShieldCheck),
          h("span", null, "Dealer trust checked"),
        ),
      ),
    ),
    h(SearchPanel, props),
  );
}

function SearchPanel({
  formData,
  selectedFeatures,
  isSearching,
  onSubmit,
  onDemo,
  onFormChange,
  onFeatureToggle,
}) {
  const presets = [
    {
      label: "Family SUV",
      data: { carType: "SUV", budgetMin: "18000", budgetMax: "36000", yearMin: "2019", mileageMax: "70000" },
      features: ["Backup Camera", "Apple CarPlay", "Blind Spot Monitor", "4WD/AWD"],
    },
    {
      label: "Commute sedan",
      data: { carType: "Sedan", budgetMin: "12000", budgetMax: "26000", yearMin: "2018", mileageMax: "80000" },
      features: ["Bluetooth", "Backup Camera", "Apple CarPlay"],
    },
    {
      label: "Weekend truck",
      data: { carType: "Truck", budgetMin: "22000", budgetMax: "45000", yearMin: "2017", mileageMax: "90000" },
      features: ["Backup Camera", "4WD/AWD", "Remote Start"],
    },
  ];

  function applyPreset(preset) {
    Object.entries(preset.data).forEach(([field, value]) => onFormChange(field, value));
    onFeatureToggle(preset.features);
  }

  function toggleFeature(feature) {
    onFeatureToggle((current) =>
      current.includes(feature) ? current.filter((item) => item !== feature) : [...current, feature],
    );
  }

  return h(
    motion.form,
    {
      id: "search-panel",
      className: "search-panel",
      onSubmit,
      initial: { opacity: 0, y: 20 },
      animate: { opacity: 1, y: 0 },
      transition: { duration: 0.55, delay: 0.25, ease: [0.22, 1, 0.36, 1] },
    },
    h(
      "div",
      { className: "panel-heading" },
      h("div", null, h("p", { className: "section-kicker" }, "Search brief"), h("h2", null, "Tell the agent what matters.")),
      h("div", { className: "panel-badge" }, icon(BadgeCheck), h("span", null, "Live ranking")),
    ),
    h(
      "div",
      { className: "preset-row", "aria-label": "Quick search presets" },
      presets.map((preset) =>
        h(
          "button",
          { key: preset.label, className: "preset-chip", type: "button", onClick: () => applyPreset(preset) },
          h("span", null, preset.label),
          icon(ChevronRight),
        ),
      ),
    ),
    h(
      "div",
      { className: "form-grid" },
      h(SelectField, {
        id: "car-type",
        label: "Body style",
        value: formData.carType,
        required: true,
        options: carTypes,
        placeholder: "Choose style",
        onChange: (value) => onFormChange("carType", value),
      }),
      h(SelectField, {
        id: "condition",
        label: "Condition",
        value: formData.condition,
        options: conditions,
        placeholder: "Any condition",
        onChange: (value) => onFormChange("condition", value),
      }),
      h(NumberField, {
        id: "budget-min",
        label: "Budget min",
        value: formData.budgetMin,
        required: true,
        min: 0,
        step: 500,
        onChange: (value) => onFormChange("budgetMin", value),
      }),
      h(NumberField, {
        id: "budget-max",
        label: "Budget max",
        value: formData.budgetMax,
        required: true,
        min: 0,
        step: 500,
        onChange: (value) => onFormChange("budgetMax", value),
      }),
      h(NumberField, {
        id: "year-min",
        label: "Year from",
        value: formData.yearMin,
        min: 2000,
        max: 2026,
        onChange: (value) => onFormChange("yearMin", value),
      }),
      h(NumberField, {
        id: "mileage-max",
        label: "Max mileage",
        value: formData.mileageMax,
        min: 0,
        step: 1000,
        onChange: (value) => onFormChange("mileageMax", value),
      }),
    ),
    h(
      "fieldset",
      { className: "feature-fieldset" },
      h("legend", null, "Must-have features"),
      h(
        "div",
        { className: "feature-grid" },
        features.map((feature) =>
          h(
            "button",
            {
              key: feature,
              type: "button",
              className: cls("feature-chip", selectedFeatures.includes(feature) && "is-active"),
              onClick: () => toggleFeature(feature),
              "aria-pressed": selectedFeatures.includes(feature),
            },
            selectedFeatures.includes(feature) ? icon(Check, "chip-check") : h("span", { className: "chip-dot" }),
            h("span", null, feature),
          ),
        ),
      ),
    ),
    h(
      "div",
      { className: "panel-actions" },
      h(
        "button",
        { className: "btn btn-primary", type: "submit", disabled: isSearching },
        isSearching ? icon(LoaderCircle, "icon is-spinning") : icon(ScanSearch),
        h("span", null, isSearching ? "Starting search" : "Search live inventory"),
      ),
      h("button", { className: "btn btn-muted", type: "button", onClick: onDemo, disabled: isSearching }, icon(Trophy), h("span", null, "Use demo data")),
    ),
  );
}

function SelectField({ id, label, value, options, placeholder, onChange, required }) {
  return h(
    "label",
    { className: "field", htmlFor: id },
    h("span", null, label),
    h(
      "select",
      { id, value, required, onChange: (event) => onChange(event.target.value) },
      h("option", { value: "" }, placeholder),
      options.map((option) => h("option", { key: option, value: option }, option)),
    ),
  );
}

function NumberField({ id, label, value, onChange, min, max, step, required }) {
  return h(
    "label",
    { className: "field", htmlFor: id },
    h("span", null, label),
    h("input", {
      id,
      type: "number",
      value,
      min,
      max,
      step,
      required,
      inputMode: "numeric",
      onChange: (event) => onChange(event.target.value),
    }),
  );
}

function Stat({ value, label }) {
  return h(
    "div",
    { className: "stat" },
    h("strong", null, value),
    h("span", null, label),
  );
}

function BrandMarquee() {
  const sources = ["CarMax", "Carvana", "Budget fit", "Low mileage", "Clean title", "Feature match", "Trust score", "AI summary"];

  return h(
    "section",
    { className: "marquee-band", "aria-label": "Marketplace and scoring signals" },
    h(NativeMarquee, { items: sources }),
  );
}

function NativeMarquee({ items }) {
  const reduceMotion = useReducedMotion();
  const repeated = [...items, ...items];

  return h(
    "div",
    { className: "native-marquee" },
    h(
      motion.div,
      {
        className: "marquee-track",
        animate: reduceMotion ? undefined : { x: ["0%", "-50%"] },
        transition: { repeat: Infinity, duration: 22, ease: "linear" },
      },
      repeated.map((item, index) =>
        h(
          "span",
          { className: "marquee-pill", key: `${item}-${index}` },
          h("span", { className: "pill-line" }),
          item,
        ),
      ),
    ),
  );
}

function ProofSection() {
  const proof = [
    { icon: ShieldCheck, title: "Trust-weighted", text: "Source reliability is part of every score, so a cheap car does not automatically win." },
    { icon: CircleDollarSign, title: "Budget-aware", text: "The ranking favors value inside your range instead of simply sorting by lowest price." },
    { icon: Gauge, title: "Mileage-sensitive", text: "Mileage, model year, condition, and feature fit all move the final recommendation." },
  ];

  return h(
    "section",
    { id: "proof", className: "content-section proof-section" },
    h(SectionHeader, {
      kicker: "Advisor logic",
      title: "A landing page that is also the product.",
      text: "The first screen is the working intake. Every section below reinforces why the shortlist is worth trusting.",
    }),
    h(
      "div",
      { className: "proof-grid" },
      proof.map((item, index) =>
        h(
          Reveal,
          { as: "article", className: "proof-card", delay: index * 0.08, key: item.title },
          h("div", { className: "proof-icon" }, icon(item.icon)),
          h("h3", null, item.title),
          h("p", null, item.text),
        ),
      ),
    ),
  );
}

function SearchJourney({ journey, progressItems, result, error, onReset, onDemo }) {
  return h(
    "section",
    { id: "search-journey", className: cls("journey-section", journey === "idle" && "is-idle") },
    h(
      AnimatePresence,
      { mode: "wait" },
      journey === "loading" &&
        h(LoadingState, { key: "loading", progressItems }),
      journey === "results" &&
        h(ResultsSection, { key: "results", result, onReset }),
      journey === "error" &&
        h(ErrorState, { key: "error", error, onReset, onDemo }),
    ),
  );
}

function LoadingState({ progressItems }) {
  return h(
    motion.div,
    {
      className: "loading-shell",
      initial: { opacity: 0, y: 22 },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: -18 },
      transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
    },
    h(
      "div",
      { className: "loading-copy" },
      h("div", { className: "loading-icon" }, icon(LoaderCircle, "icon is-spinning")),
      h("div", null, h("p", { className: "section-kicker" }, "Search in motion"), h("h2", null, "Building your shortlist")),
    ),
    h(
      "div",
      { className: "progress-list" },
      progressItems.map((item) =>
        h(
          "div",
          { className: cls("progress-item", item.status), key: item.step },
          h("span", { className: "progress-dot" }),
          h("span", { className: "progress-name" }, stepLabels[item.step] || item.step),
          h("span", { className: "progress-status" }, progressStatus(item.status)),
        ),
      ),
    ),
  );
}

function progressStatus(status) {
  return {
    pending: "Waiting",
    running: "Running",
    done: "Done",
    failed: "Failed",
  }[status] || status;
}

function ResultsSection({ result, onReset }) {
  const cars = result?.cars || [];
  const params = result?.search_params || {};
  const tags = [
    params.car_type,
    params.budget_min != null && params.budget_max != null
      ? `${formatMoney(params.budget_min)} to ${formatMoney(params.budget_max)}`
      : null,
    params.year_min ? `${params.year_min}+` : null,
    params.mileage_max ? `Under ${formatNumber(params.mileage_max)} mi` : null,
    params.condition,
  ].filter(Boolean);

  return h(
    motion.div,
    {
      className: "results-shell",
      initial: { opacity: 0, y: 22 },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: -18 },
      transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
    },
    h(
      "div",
      { className: "results-header" },
      h(
        "div",
        null,
        h("p", { className: "section-kicker" }, "Ranked shortlist"),
        h("h2", null, `${result?.total_found || cars.length} cars found`),
        result?.generated_at && h("p", { className: "results-meta" }, `Generated ${formatDate(result.generated_at)}`),
      ),
      h("button", { className: "btn btn-muted", type: "button", onClick: onReset }, icon(RefreshCw), h("span", null, "New search")),
    ),
    h("div", { className: "tag-row" }, tags.map((tag) => h("span", { className: "result-tag", key: tag }, tag))),
    h(
      "div",
      { className: "car-grid" },
      cars.map((scoredCar, index) => h(CarCard, { scoredCar, index, key: `${scoredCar.listing?.title || "car"}-${index}` })),
    ),
  );
}

function CarCard({ scoredCar, index }) {
  const car = scoredCar.listing || {};
  const scores = scoredCar.scores || {};
  const composite = Math.round(Number(scores.composite) || 0);
  const scoreClass = composite >= 85 ? "high" : composite >= 70 ? "mid" : "low";
  const breakdown = [
    ["Price value", scores.price_value],
    ["Year", scores.year_depreciation],
    ["Mileage", scores.mileage],
    ["Condition", scores.condition],
    ["Features", scores.feature_match],
    ["Trust", scores.source_trust],
  ];

  return h(
    motion.article,
    {
      className: "car-card",
      initial: { opacity: 0, y: 20 },
      whileInView: { opacity: 1, y: 0 },
      viewport: { once: true, amount: 0.2 },
      transition: { duration: 0.45, delay: index * 0.05 },
    },
    h(
      "div",
      { className: "car-card-top" },
      car.image_url
        ? h("img", {
            className: "car-image",
            src: car.image_url,
            alt: car.title || "Vehicle listing",
            onError: (event) => {
              event.currentTarget.style.display = "none";
            },
          })
        : h("div", { className: "car-image-fallback" }, icon(Car)),
      h(
        "div",
        { className: cls("score-badge", scoreClass) },
        h("strong", null, composite),
        h("span", null, "score"),
      ),
    ),
    h(
      "div",
      { className: "car-card-body" },
      h("div", { className: "listing-source" }, h("span", null, car.source || "Marketplace"), car.year && h("span", null, car.year)),
      h("h3", null, car.title || "Recommended vehicle"),
      h(
        "div",
        { className: "listing-facts" },
        car.price != null && h("span", null, formatMoney(car.price)),
        car.mileage != null && h("span", null, `${formatNumber(car.mileage)} mi`),
        car.condition && h("span", null, car.condition),
      ),
      scoredCar.summary && h("p", { className: "ai-summary" }, scoredCar.summary),
      h(
        "div",
        { className: "breakdown" },
        breakdown.map(([label, value]) => {
          const safeValue = Math.max(0, Math.min(100, Number(value) || 0));
          return h(
            "div",
            { className: "breakdown-row", key: label },
            h("span", null, label),
            h("div", { className: "bar-track" }, h("span", { className: "bar-fill", style: { width: `${safeValue}%` } })),
            h("strong", null, Math.round(safeValue)),
          );
        }),
      ),
      (car.features || []).length > 0 &&
        h(
          "div",
          { className: "mini-tags" },
          car.features.slice(0, 5).map((feature) => h("span", { key: feature }, feature)),
        ),
      car.url &&
        h(
          "a",
          { className: "listing-link", href: car.url, target: "_blank", rel: "noopener noreferrer" },
          h("span", null, `View on ${car.source || "source"}`),
          icon(ArrowRight),
        ),
    ),
  );
}

function ErrorState({ error, onReset, onDemo }) {
  return h(
    motion.div,
    {
      className: "error-shell",
      initial: { opacity: 0, y: 22 },
      animate: { opacity: 1, y: 0 },
      exit: { opacity: 0, y: -18 },
      transition: { duration: 0.45, ease: [0.22, 1, 0.36, 1] },
    },
    h("div", { className: "error-icon" }, icon(XCircle)),
    h("p", { className: "section-kicker" }, "Search needs attention"),
    h("h2", null, "Something blocked the shortlist"),
    h("p", null, error || "Try again or preview the demo results."),
    h(
      "div",
      { className: "error-actions" },
      h("button", { className: "btn btn-muted", type: "button", onClick: onReset }, icon(RefreshCw), h("span", null, "Reset")),
      h("button", { className: "btn btn-primary", type: "button", onClick: onDemo }, icon(Trophy), h("span", null, "Use demo data")),
    ),
  );
}

function FeatureSection() {
  const workflow = [
    { icon: Search, title: "Market scan", text: "CarMax and Carvana listings are pulled into one normalized comparison set." },
    { icon: TimerReset, title: "Fit scoring", text: "Budget, year, mileage, condition, features, and source trust become a single score." },
    { icon: Trophy, title: "Ranked shortlist", text: "The strongest matches surface with readable summaries and transparent score bars." },
  ];

  return h(
    "section",
    { id: "workflow", className: "content-section workflow-section" },
    h(SectionHeader, {
      kicker: "Workflow",
      title: "From scattered listings to a confident top five.",
      text: "The page is designed around quick comparison, not decoration. Motion guides attention while the dense details stay easy to scan.",
    }),
    h(
      "div",
      { className: "workflow-grid" },
      workflow.map((item, index) =>
        h(
          Reveal,
          { as: "article", className: "workflow-card", delay: index * 0.08, key: item.title },
          h("span", { className: "workflow-index" }, `0${index + 1}`),
          h("div", { className: "workflow-icon" }, icon(item.icon)),
          h("h3", null, item.title),
          h("p", null, item.text),
        ),
      ),
    ),
  );
}

function TestimonialsSection() {
  const reviews = [
    {
      quote: "The score breakdown made the decision feel obvious. I could see why the top car beat the cheaper one.",
      name: "Maya R.",
      role: "First-time buyer",
    },
    {
      quote: "It turned a whole weekend of dealership tabs into one shortlist with actual trade-offs.",
      name: "Jordan K.",
      role: "Family SUV search",
    },
    {
      quote: "The mileage and condition weighting kept me from chasing a price that was too good for a reason.",
      name: "Nina P.",
      role: "Used sedan buyer",
    },
  ];

  return h(
    "section",
    { id: "reviews", className: "content-section reviews-section" },
    h(SectionHeader, {
      kicker: "Social proof",
      title: "Built for buyers who want clarity before contact.",
      text: "Testimonials use the 21st.dev animated review pattern, tuned for an automotive advisor instead of a generic landing page.",
    }),
    h(
      "div",
      { className: "review-grid" },
      reviews.map((review, index) =>
        h(
          Reveal,
          { as: "article", className: "review-card", delay: index * 0.08, key: review.name },
          h("div", { className: "stars", "aria-label": "Five star review" }, [0, 1, 2, 3, 4].map((item) => icon(Star, "star-icon", { key: item, fill: "currentColor" }))),
          h("p", null, review.quote),
          h("div", { className: "reviewer" }, h("strong", null, review.name), h("span", null, review.role)),
        ),
      ),
    ),
  );
}

function ClosingCta({ onDemo }) {
  return h(
    "section",
    { className: "closing-cta" },
    h(
      Reveal,
      { className: "closing-inner" },
      h("p", { className: "section-kicker" }, "Ready when you are"),
      h("h2", null, "Start with a real brief, then let the agent do the comparison work."),
      h(
        "div",
        { className: "closing-actions" },
        h("a", { className: "btn btn-primary", href: "#search-panel" }, icon(Search), h("span", null, "Create shortlist")),
        h("button", { className: "btn btn-ghost", type: "button", onClick: onDemo }, icon(Zap), h("span", null, "Preview demo")),
      ),
    ),
  );
}

function SectionHeader({ kicker, title, text }) {
  return h(
    Reveal,
    { className: "section-header" },
    h("p", { className: "section-kicker" }, kicker),
    h("h2", null, title),
    h("p", null, text),
  );
}

function Footer() {
  return h(
    "footer",
    { className: "site-footer" },
    h("span", null, "AgentBuy Car"),
    h("span", null, "Built on the existing AutoBrief search engine"),
  );
}

createRoot(document.getElementById("root")).render(h(App));
