import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Receipt } from "lucide-react";

export default function PatientBilling() {
  const [items, setItems] = React.useState([]);
  React.useEffect(() => { api.get("/invoices").then((r) => setItems(r.data || [])); }, []);

  return (
    <PortalLayout>
      <PortalHeader title="Billing" subtitle="Your invoices and receipts." />
      {items.length === 0 ? (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] p-10 text-center text-[#6a6a6a]">
          <Receipt size={28} className="mx-auto text-[#c19a4b]" />
          <div className="mt-3">No invoices yet.</div>
        </div>
      ) : (
        <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
              <tr><th className="text-left py-3 px-4">Date</th><th className="text-left py-3 px-4">Description</th><th className="text-right py-3 px-4">Amount</th><th className="text-left py-3 px-4">Status</th><th className="text-left py-3 px-4">Paid via</th></tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="border-t border-[#e7dfc9]">
                  <td className="py-3 px-4 text-[#6a6a6a]">{new Date(i.created_at).toLocaleDateString()}</td>
                  <td className="py-3 px-4">{i.description}</td>
                  <td className="py-3 px-4 text-right">${i.amount.toFixed(2)}</td>
                  <td className="py-3 px-4"><span className={`text-xs px-2 py-0.5 rounded-full ${i.status === "paid" ? "bg-[#e7dfc9] text-[#2f4a3a]" : "bg-[#fbf2d9] text-[#6b4a1c]"}`}>{i.status}</span></td>
                  <td className="py-3 px-4 text-xs text-[#6a6a6a]">{i.payment_method ? i.payment_method.replace("_", " ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PortalLayout>
  );
}
