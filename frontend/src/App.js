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
            <Route path="/portal/patient/security" element={<Protected roles={["client"]}><Security /></Protected>} />

            {/* Provider & staff */}
            <Route path="/portal/provider" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderDashboard /></Protected>} />
            <Route path="/portal/provider/patients" element={<Protected roles={["practitioner", "staff", "admin"]}><PatientsList /></Protected>} />
            <Route path="/portal/provider/patients/:id" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderPatientChart /></Protected>} />
            <Route path="/portal/provider/schedule" element={<Protected roles={["practitioner", "staff", "admin"]}><ProviderSchedule /></Protected>} />
            <Route path="/portal/provider/availability" element={<Protected roles={["practitioner", "admin"]}><Availability /></Protected>} />
            <Route path="/portal/provider/messages" element={<Protected roles={["practitioner", "admin"]}><Messages /></Protected>} />
            <Route path="/portal/provider/security" element={<Protected roles={["practitioner", "staff", "admin"]}><Security /></Protected>} />

            {/* Admin */}
            <Route path="/portal/admin" element={<Protected roles={["admin"]}><AdminOverview /></Protected>} />
            <Route path="/portal/admin/users" element={<Protected roles={["admin"]}><AdminUsers /></Protected>} />
            <Route path="/portal/admin/audit" element={<Protected roles={["admin"]}><AdminAudit /></Protected>} />
            <Route path="/portal/admin/reminders" element={<Protected roles={["admin"]}><AdminReminders /></Protected>} />
            <Route path="/portal/admin/security" element={<Protected roles={["admin"]}><Security /></Protected>} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
