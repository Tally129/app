// Mock data for Natural Medical Solutions concierge site

export const brand = {
  name: "Natural Medical Solutions",
  subName: "Wellness Center",
  tagline: "Rooted in your well-being",
  subTag: "Naturopathic Medicine \u00B7 Holistic Care",
  phone: "(770) 674-6311",
  address: "1130 Upper Hembree Rd, Roswell, GA 30076"
};

export const heroCopy = {
  eyebrow: "NATURAL MEDICAL SOLUTIONS \u00B7 WELLNESS CENTER",
  title: "Holistic care, personally prescribed",
  body: "Every protocol is hand-curated by Dr. Ravello\u2019s team to address the root cause \u2014 mind, body and spirit."
};

export const membershipTiers = [
  {
    id: "essentials",
    name: "Essentials Wellness",
    price: 99,
    cadence: "/ month",
    blurb: "Monthly check-ins with a naturopathic doctor \u2014 ideal for clients beginning their holistic journey.",
    perks: [
      "1 naturopathic consult per month",
      "Seasonal detox guidance included",
      "10% off supplements"
    ],
    featured: false
  },
  {
    id: "core",
    name: "Core Wellness",
    price: 199,
    cadence: "/ month",
    blurb: "Advanced protocols and targeted testing \u2014 for clients ready to address chronic imbalances.",
    perks: [
      "1 advanced consult + lab review",
      "Hormone or thyroid panel included quarterly",
      "15% off treatments & supplements"
    ],
    featured: true
  },
  {
    id: "vip",
    name: "VIP Wellness",
    price: 299,
    cadence: "/ month",
    blurb: "Concierge-level holistic care \u2014 twice-monthly visits with priority access to Dr. Ravello.",
    perks: [
      "2 consults per month",
      "Thermography + IV drip included",
      "20% off all services"
    ],
    featured: false
  }
];

export const services = [
  { id: "naturopathic", name: "Naturopathic Medicine" },
  { id: "hormones", name: "Hormone Balancing" },
  { id: "thyroid", name: "Thyroid Care" },
  { id: "detox", name: "Detoxification" },
  { id: "nutrition", name: "Nutrition & Weight Loss" },
  { id: "homeopathic", name: "Homeopathic Medicine" },
  { id: "integrative", name: "Integrative Medicine" },
  { id: "pain", name: "Natural Pain Management" },
  { id: "thermography", name: "Thermography" },
  { id: "prevention", name: "Disease Prevention" }
];

export const conditions = [
  { id: "adrenal", name: "Adrenal Fatigue" },
  { id: "allergies", name: "Allergies & Autoimmune" },
  { id: "brain", name: "Brain Health" },
  { id: "diabetes", name: "Diabetes" },
  { id: "digestive", name: "Digestive Health" },
  { id: "heart", name: "Heart Health" },
  { id: "thyroid", name: "Thyroid Health" }
];

export const addOns = [
  { id: "iv", name: "IV Nutrient Drip", price: 95 },
  { id: "thermo", name: "Thermography Scan", price: 125 },
  { id: "bioscan", name: "Bio-Energetic Scan", price: 75 },
  { id: "ozone", name: "Ozone Therapy", price: 90 }
];

export const testimonials = [
  {
    quote: "I love the passion. She gives you the time to truly listen to your problem.",
    author: "Yeni"
  },
  {
    quote: "You\u2019re not just another number \u2014 Dr. Ravello really listens and cares. It feels like family here.",
    author: "Nicholas"
  },
  {
    quote: "I would highly recommend Natural Medical Solutions and Dr. Ravello to everybody.",
    author: "Kathy"
  },
  {
    quote: "Feels like a miracle has happened to me. I recommended her to my wife and she\u2019s doing better too.",
    author: "Carl"
  }
];

export const hours = [
  { day: "Mon", time: "9:00 AM \u2013 5:00 PM" },
  { day: "Tue", time: "9:00 AM \u2013 5:00 PM" },
  { day: "Wed", time: "9:00 AM \u2013 5:00 PM" },
  { day: "Thu", time: "10:00 AM \u2013 6:00 PM" },
  { day: "Fri", time: "9:00 AM \u2013 1:00 PM" },
  { day: "Sat", time: "Closed" },
  { day: "Sun", time: "Closed" }
];

export const LS_KEYS = {
  appointments: "nms_appointments",
  vip: "nms_vip_list",
  clients: "nms_clients",
  session: "nms_session"
};
