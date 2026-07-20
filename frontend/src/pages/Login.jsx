import React from "react";
import Footer from "../components/Footer";
import AuthCard from "../components/AuthCard";

export default function Login() {
  return (
    <>
      <AuthCard
        variant="patient"
        title="Patient Portal"
        subtitle="Access your appointments, chart, labs, and secure messages."
        redirectPath="/login"
        crossPortalTo="/staff-login"
        crossPortalLabel="Staff & providers:"
        crossPortalLinkText="sign in here"
      />
      <Footer />
    </>
  );
}
