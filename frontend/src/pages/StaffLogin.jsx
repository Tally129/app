import React from "react";
import AuthCard from "../components/AuthCard";

export default function StaffLogin() {
  return (
    <AuthCard
      variant="staff"
      title="Staff & Provider Portal"
      subtitle="Front desk · medical assistants · practitioners · admins."
      redirectPath="/staff-login"
      crossPortalTo="/login"
      crossPortalLabel="Patient?"
      crossPortalLinkText="Sign in to the patient portal"
    />
  );
}
