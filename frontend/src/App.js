import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import RequestAppointment from "./pages/RequestAppointment";
import Signup from "./pages/Signup";
import Login from "./pages/Login";
import PortalIndex from "./pages/PortalIndex";
import PatientDashboard from "./pages/patient/PatientDashboard";
import PatientIntake from "./pages/patient/PatientIntake";
import PatientChart from "./pages/patient/PatientChart";
import PatientFiles from "./pages/patient/PatientFiles";
import PatientAppointments from "./pages/patient/PatientAppointments";
import PatientBilling from "./pages/patient/PatientBilling";
import PatientPlan from "./pages/patient/PatientPlan";
import PatientSymptoms from "./pages/patient/PatientSymptoms";
import PatientLabs from "./pages/patient/PatientLabs";
import Security from "./pages/portal/Security";
import Messages from "./pages/portal/Messages";
import ProviderDashboard from "./pages/provider/ProviderDashboard";
import PatientsList from "./pages/provider/PatientsList";
import ProviderPatientChart from "./pages/provider/PatientChart";
import ProviderSchedule from "./pages/provider/ProviderSchedule";
import Availability from "./pages/provider/Availability";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminUsers from "./pages/admin/AdminUsers";
import AdminAudit from "./pages/admin/AdminAudit";
import AdminReminders from "./pages/admin/AdminReminders";
import TelehealthVisit from "./pages/TelehealthVisit";
import MyAccount from "./pages/portal/MyAccount";
import FrontDesk from "./pages/portal/FrontDesk";
import PointOfSale from "./pages/portal/PointOfSale";
import Treatments from "./pages/portal/Treatments";
import TimeClock from "./pages/portal/TimeClock";
import Inventory from "./pages/portal/Inventory";
import Transactions from "./pages/portal/Transactions";
import ImportClients from "./pages/portal/ImportClients";
import Analytics from "./pages/portal/Analytics";
import { Toaster } from "./components/ui/toaster";
import { AuthProvider } from "./lib/auth";
import { Protected } from "./lib/Protected";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public marketing */}
            <Route path="/" element={<Home />} />
            <Route path="/request-appointment" element={<RequestAppointment />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/login" element={<Login />} />

            {/* Portal redirect */}
            <Route path="/portal" element={<PortalIndex />} />

            {/* Telehealth */}
            <Route path="/portal/visit/:id" element={
              <Protected roles={["client", "practitioner", "staff", "admin"]}><TelehealthVisit /></Protected>
            } />

            {/* Patient */}
            <Route path="/portal/patient" element={<Protected roles={["client"]}><PatientDashboard /></Protected>} />
            <Route path="/portal/patient/intake" element={<Protected roles={["client"]}><PatientIntake /></Protected>} />
            <Route path="/portal/patient/chart" element={<Protected roles={["client"]}><PatientChart /></Protected>} />
            <Route path="/portal/patient/files" element={<Protected roles={["client"]}><PatientFiles /></Protected>} />
            <Route path="/portal/patient/appointments" element={<Protected roles={["client"]}><PatientAppointments /></Protected>} />
            <Route path="/portal/patient/billing" element={<Protected roles={["client"]}><PatientBilling /></Protected>} />
            <Route path="/portal/patient/plan" element={<Protected roles={["client"]}><PatientPlan /></Protected>} />
            <Route path="/portal/patient/symptoms" element={<Protected roles={["client"]}><PatientSymptoms /></Protected>} />
            <Route path="/portal/patient/labs" element={<Protected roles={["client"]}><PatientLabs /></Protected>} />
            <Route path="/portal/patient/messages" element={<Protected roles={["client"]}><Messages /></Protected>} />
            <Route path="/portal/patient/account" element={<Protected roles={["client"]}><MyAccount /></Protected>} />
            <Route path="/portal/patient/security" element={<Protected roles={["client"]}><Security /></Protected>} />

            {/* Provider & staff */}
            <Route path="/portal/provider" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderDashboard /></Protected>} />
            <Route path="/portal/provider/patients" element={<Protected roles={["practitioner", "staff", "admin"]}><PatientsList /></Protected>} />
            <Route path="/portal/provider/patients/:id" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderPatientChart /></Protected>} />
            <Route path="/portal/provider/schedule" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderSchedule /></Protected>} />
            <Route path="/portal/provider/availability" element={<Protected roles={["practitioner", "admin"]}><Availability /></Protected>} />
            <Route path="/portal/provider/messages" element={<Protected roles={["practitioner", "admin"]}><Messages /></Protected>} />
            <Route path="/portal/provider/security" element={<Protected roles={["practitioner", "staff", "admin"]}><Security /></Protected>} />
            <Route path="/portal/provider/account" element={<Protected roles={["practitioner", "staff", "admin"]}><MyAccount /></Protected>} />
            <Route path="/portal/provider/front-desk" element={<Protected roles={["practitioner", "staff", "admin"]}><FrontDesk /></Protected>} />
            <Route path="/portal/provider/time-clock" element={<Protected roles={["practitioner", "staff", "admin"]}><TimeClock /></Protected>} />
            <Route path="/portal/provider/treatments" element={<Protected roles={["practitioner", "staff", "admin"]}><Treatments /></Protected>} />
            <Route path="/portal/provider/pos" element={<Protected roles={["staff", "admin"]}><PointOfSale /></Protected>} />
            <Route path="/portal/provider/transactions" element={<Protected roles={["staff", "admin"]}><Transactions /></Protected>} />
            <Route path="/portal/provider/inventory" element={<Protected roles={["staff", "admin"]}><Inventory /></Protected>} />

            {/* Admin */}
            <Route path="/portal/admin" element={<Protected roles={["admin"]}><AdminOverview /></Protected>} />
            <Route path="/portal/admin/users" element={<Protected roles={["admin"]}><AdminUsers /></Protected>} />
            <Route path="/portal/admin/audit" element={<Protected roles={["admin"]}><AdminAudit /></Protected>} />
            <Route path="/portal/admin/reminders" element={<Protected roles={["admin"]}><AdminReminders /></Protected>} />
            <Route path="/portal/admin/security" element={<Protected roles={["admin"]}><Security /></Protected>} />
            <Route path="/portal/admin/account" element={<Protected roles={["admin"]}><MyAccount /></Protected>} />
            <Route path="/portal/admin/front-desk" element={<Protected roles={["admin"]}><FrontDesk /></Protected>} />
            <Route path="/portal/admin/time-clock" element={<Protected roles={["admin"]}><TimeClock /></Protected>} />
            <Route path="/portal/admin/treatments" element={<Protected roles={["admin"]}><Treatments /></Protected>} />
            <Route path="/portal/admin/pos" element={<Protected roles={["admin"]}><PointOfSale /></Protected>} />
            <Route path="/portal/admin/transactions" element={<Protected roles={["admin"]}><Transactions /></Protected>} />
            <Route path="/portal/admin/inventory" element={<Protected roles={["admin"]}><Inventory /></Protected>} />
            <Route path="/portal/admin/import-clients" element={<Protected roles={["admin"]}><ImportClients /></Protected>} />
            <Route path="/portal/admin/analytics" element={<Protected roles={["admin"]}><Analytics /></Protected>} />
            <Route path="/portal/provider/analytics" element={<Protected roles={["practitioner", "admin"]}><Analytics /></Protected>} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
