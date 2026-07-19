import React from "react";
import PortalLayout, { PortalHeader } from "../PortalLayout";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { useToast } from "../../hooks/use-toast";
import { UserPlus } from "lucide-react";
import { getErrorMessage } from "../../lib/errors";

const ROLES = ["admin", "practitioner", "staff", "client"];

export default function AdminUsers() {
  const { toast } = useToast();
  const [users, setUsers] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [creating, setCreating] = React.useState(false);
  const [form, setForm] = React.useState({ full_name: "", email: "", password: "", role: "practitioner", phone: "" });

  const load = () => api.get("/admin/users").then((r) => setUsers(r.data || [])).finally(() => setLoading(false));
  React.useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.email || !form.full_name || form.password.length < 8) {
      toast({ title: "Fill all fields (password 8+ chars)" });
      return;
    }
    try {
      await api.post("/admin/users", form);
      toast({ title: "User created" });
      setForm({ full_name: "", email: "", password: "", role: "practitioner", phone: "" });
      setCreating(false);
      load();
    } catch (e) {
      toast({ title: "Failed", description: getErrorMessage(e) || "" });
    }
  };

  const changeRole = async (u, role) => {
    try {
      await api.put(`/admin/users/${u.id}/role`, { role });
      toast({ title: `Role set to ${role}` });
      load();
    } catch {
      toast({ title: "Failed" });
    }
  };

  return (
    <PortalLayout>
      <PortalHeader
        title="Users & Roles"
        subtitle={`${users.length} users`}
        actions={
          <Button onClick={() => setCreating((v) => !v)} className="btn-lift h-11 rounded-full bg-[#2f4a3a] hover:bg-[#263d30] text-[#f6f1e6]">
            <UserPlus size={16} className="mr-2" /> Add user
          </Button>
        }
      />

      {creating && (
        <div className="mb-6 rounded-2xl border border-[#c19a4b] bg-[#fbf7ee] p-5 grid md:grid-cols-2 gap-4">
          <div><Label>Full name</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div><Label>Email</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div><Label>Password (8+)</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <div><Label>Phone</Label><Input className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
          <div><Label>Role</Label>
            <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
              <SelectTrigger className="mt-2 bg-[#f6f1e6] border-[#e0d6bc]"><SelectValue /></SelectTrigger>
              <SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2 flex justify-end">
            <Button onClick={create} className="btn-lift rounded-full bg-[#c19a4b] hover:bg-[#a8853f] text-[#1f2a22]">Create user</Button>
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-[#e7dfc9] bg-[#fbf7ee] overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f1ead8] text-[#8a6a3c] uppercase text-[11px] tracking-widest">
            <tr>
              <th className="text-left py-3 px-4">Name</th>
              <th className="text-left py-3 px-4">Email</th>
              <th className="text-left py-3 px-4">Role</th>
              <th className="text-left py-3 px-4">MFA</th>
              <th className="text-left py-3 px-4">Last login</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={5} className="py-8 text-center text-[#6a6a6a]">Loading…</td></tr>}
            {users.map((u) => (
              <tr key={u.id} className="border-t border-[#e7dfc9]">
                <td className="py-3 px-4">{u.full_name}</td>
                <td className="py-3 px-4 text-[#3a3a3a]">{u.email}</td>
                <td className="py-3 px-4">
                  <Select value={u.role} onValueChange={(v) => changeRole(u, v)}>
                    <SelectTrigger className="h-8 w-36 bg-[#f6f1e6] border-[#e0d6bc] text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>{ROLES.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="py-3 px-4 text-xs">
                  {u.mfa_enabled ? <span className="text-[#2f4a3a]">Enabled</span> : <span className="text-[#8a6a3c]">Off</span>}
                </td>
                <td className="py-3 px-4 text-[#6a6a6a] text-xs">
                  {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PortalLayout>
  );
}