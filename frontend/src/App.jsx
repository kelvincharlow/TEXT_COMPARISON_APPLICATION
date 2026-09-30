import Dashboard from "./Dashboard.jsx";
import AccountGate from "./AccountGate.jsx";
import Administration from "./Administration.jsx";

export default function App() {
  return <AccountGate>{(user, session) => user.roles.includes("administrator")
    ? <Administration key={user.id} user={user} onSignOut={session.signOut} />
    : <Dashboard key={user.id} user={user} onSignOut={session.signOut} />}</AccountGate>;
}
