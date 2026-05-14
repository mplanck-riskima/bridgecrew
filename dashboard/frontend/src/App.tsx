import { Route, Routes } from "react-router";
import Layout from "./components/Layout";
import RequireAuth from "./components/RequireAuth";
import Costs from "./pages/Costs";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import Prompts from "./pages/Prompts";
import Schedules from "./pages/Schedules";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id" element={<ProjectDetail />} />
        <Route path="prompts" element={<Prompts />} />
        <Route path="schedules" element={<Schedules />} />
        <Route path="costs" element={<Costs />} />
      </Route>
    </Routes>
  );
}
