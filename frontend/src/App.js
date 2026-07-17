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
import AdminSessionExplorer from "./pages/admin/AdminSessionExplorer";
import AdminReminders from "./pages/admin/AdminReminders";
import AdminNotesList from "./pages/admin/AdminNotesList";
import AdminFilesList from "./pages/admin/AdminFilesList";
import AdminFormsConsents from "./pages/admin/AdminFormsConsents";
import FormResponder from "./pages/FormResponder";
import SoapNotes from "./pages/portal/SoapNotes";
import Protocols from "./pages/portal/Protocols";
import PatientProtocols from "./pages/patient/PatientProtocols";
import DocumentLibrary from "./pages/admin/DocumentLibrary";
import PushOptInBanner from "./components/PushOptInBanner";
import SessionTimeout from "./components/SessionTimeout";
import AdminCompliance from "./pages/admin/AdminCompliance";
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
import AppointmentsEHR from "./pages/provider/AppointmentsEHR";
import TelehealthHub from "./pages/portal/TelehealthHub";
import StaffLogin from "./pages/StaffLogin";
import OAuthComplete from "./pages/OAuthComplete";
import StaffDashboard from "./pages/staff/StaffDashboard";
import { Toaster } from "./components/ui/toaster";
import { AuthProvider } from "./lib/auth";
import { Protected } from "./lib/Protected";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <PushOptInBanner />
          <SessionTimeout />
          <Routes>
            {/* Public marketing */}
            <Route path="/" element={<Home />} />
            <Route path="/request-appointment" element={<RequestAppointment />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/login" element={<Login />} />
            <Route path="/staff-login" element={<StaffLogin />} />
            <Route path="/oauth-complete" element={<OAuthComplete />} />

            {/* Portal redirect */}
            <Route path="/portal" element={<PortalIndex />} />

            {/* Telehealth */}
            <Route path="/portal/visit/:id" element={
              <Protected roles={["client", "practitioner", "staff", "admin"]}><TelehealthVisit /></Protected>
            } />
            <Route path="/portal/patient/telehealth" element={<Protected roles={["client"]}><TelehealthHub /></Protected>} />
            <Route path="/portal/provider/telehealth" element={<Protected roles={["practitioner", "admin"]}><TelehealthHub /></Protected>} />
            <Route path="/portal/staff/telehealth" element={<Protected roles={["staff", "admin"]}><TelehealthHub /></Protected>} />
            <Route path="/portal/admin/telehealth" element={<Protected roles={["admin"]}><TelehealthHub /></Protected>} />

            {/* Staff portal (front-desk-first) */}
            <Route path="/portal/staff" element={<Protected roles={["staff", "admin"]}><StaffDashboard /></Protected>} />
            <Route path="/portal/staff/front-desk" element={<Protected roles={["staff", "admin"]}><FrontDesk /></Protected>} />
            <Route path="/portal/staff/appointments" element={<Protected roles={["staff", "admin"]}><AppointmentsEHR /></Protected>} />
            <Route path="/portal/staff/patients" element={<Protected roles={["staff", "admin"]}><PatientsList /></Protected>} />
            <Route path="/portal/staff/pos" element={<Protected roles={["staff", "admin"]}><PointOfSale /></Protected>} />
            <Route path="/portal/staff/transactions" element={<Protected roles={["staff", "admin"]}><Transactions /></Protected>} />
            <Route path="/portal/staff/inventory" element={<Protected roles={["staff", "admin"]}><Inventory /></Protected>} />
            <Route path="/portal/staff/treatments" element={<Protected roles={["staff", "admin"]}><Treatments /></Protected>} />
            <Route path="/portal/staff/time-clock" element={<Protected roles={["staff", "admin"]}><TimeClock /></Protected>} />
            <Route path="/portal/staff/account" element={<Protected roles={["staff", "admin"]}><MyAccount /></Protected>} />
            <Route path="/portal/staff/security" element={<Protected roles={["staff", "admin"]}><Security /></Protected>} />

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
            <Route path="/portal/provider/schedule" element={<Protected roles={["practitioner", "staff", "admin"]}><AppointmentsEHR /></Protected>} />
            <Route path="/portal/provider/appointments" element={<Protected roles={["practitioner", "staff", "admin"]}><AppointmentsEHR /></Protected>} />
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
            <Route path="/portal/admin/sessions" element={<Protected roles={["admin"]}><AdminSessionExplorer /></Protected>} />
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
            <Route path="/portal/admin/notes" element={<Protected roles={["admin", "practitioner"]}><AdminNotesList /></Protected>} />
            <Route path="/portal/admin/files" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFilesList /></Protected>} />
            <Route path="/portal/admin/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            <Route path="/portal/staff/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            <Route path="/portal/provider/forms" element={<Protected roles={["admin", "practitioner", "staff"]}><AdminFormsConsents /></Protected>} />
            {/* SOAP Notes hub (provider/admin/staff) */}
            <Route path="/portal/admin/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            <Route path="/portal/staff/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            <Route path="/portal/provider/soap" element={<Protected roles={["admin", "practitioner", "staff"]}><SoapNotes /></Protected>} />
            {/* Protocols (provider/admin only — staff read via enrollments) */}
            <Route path="/portal/admin/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            <Route path="/portal/staff/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            <Route path="/portal/provider/protocols" element={<Protected roles={["admin", "practitioner", "staff"]}><Protocols /></Protected>} />
            {/* Patient self-service */}
            <Route path="/portal/patient/protocols" element={<Protected roles={["client"]}><PatientProtocols /></Protected>} />
            {/* Document Library — universal AI ingest */}
            <Route path="/portal/admin/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/staff/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/provider/library" element={<Protected roles={["admin", "practitioner", "staff"]}><DocumentLibrary /></Protected>} />
            <Route path="/portal/admin/compliance" element={<Protected roles={["admin"]}><AdminCompliance /></Protected>} />
            <Route path="/portal/provider/analytics" element={<Protected roles={["practitioner", "admin"]}><Analytics /></Protected>} />

            {/* Public form responder (token-based, no login required) */}
            <Route path="/forms/respond/:token" element={<FormResponder />} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </div>
  );
}

export default App;
