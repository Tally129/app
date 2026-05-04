import React from "react";
import { Link } from "react-router-dom";
import { brand } from "../mock";
import { Phone, MapPin } from "lucide-react";

export default function Footer() {
  return (
    <footer className="mt-24 border-t border-[#e7dfc9] bg-[#f1ead8]">
      <div className="max-w-6xl mx-auto px-6 py-12 grid grid-cols-1 md:grid-cols-3 gap-10">
        <div>
          <div className="font-display text-xl text-[#2f4a3a]">{brand.name}</div>
          <div className="text-xs tracking-[0.25em] uppercase text-[#8a6a3c] mt-1">
            {brand.subName}
          </div>
          <p className="text-sm text-[#5c5c5c] mt-4 leading-relaxed">
            Naturopathic care rooted in whole-person healing — serving Roswell, Alpharetta & Atlanta.
          </p>
        </div>
        <div>
          <div className="eyebrow text-[#8a6a3c]">Visit</div>
          <div className="mt-3 text-sm text-[#3a3a3a] flex items-start gap-2">
            <MapPin size={16} className="mt-0.5 text-[#2f4a3a]" />
            <span>{brand.address}</span>
          </div>
          <div className="mt-2 text-sm text-[#3a3a3a] flex items-center gap-2">
            <Phone size={16} className="text-[#2f4a3a]" />
            <a href={`tel:${brand.phone.replace(/[^0-9]/g, "")}`} className="hover:text-[#2f4a3a]">
              {brand.phone}
            </a>
          </div>
        </div>
        <div>
          <div className="eyebrow text-[#8a6a3c]">Explore</div>
          <ul className="mt-3 space-y-2 text-sm">
            <li><Link to="/" className="text-[#3a3a3a] hover:text-[#2f4a3a]">Home</Link></li>
            <li><Link to="/request-appointment" className="text-[#3a3a3a] hover:text-[#2f4a3a]">Request Appointment</Link></li>
            <li><Link to="/login" className="text-[#3a3a3a] hover:text-[#2f4a3a]">Patient Portal</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-[#e7dfc9]">
        <div className="max-w-6xl mx-auto px-6 py-4 text-xs text-[#7a7a7a] flex flex-col md:flex-row justify-between items-center gap-2">
          <span>© {new Date().getFullYear()} {brand.name}. All rights reserved.</span>
          <span className="tracking-wider">Holistic · Integrative · Naturopathic</span>
        </div>
      </div>
    </footer>
  );
}
