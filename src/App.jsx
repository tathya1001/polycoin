import { useState } from "react";
import { Routes, Route } from "react-router-dom";

//pages
import Register from "./pages/RegisterPage.jsx";
import Login from "./pages/LoginPage.jsx";
import Home from "./pages/HomePage.jsx";
import Settings from "./pages/SettingsPage.jsx";
import Credit from "./pages/AddCreditPage.jsx";
import Debit from "./pages/AddDebitPage.jsx";

import "bootstrap/dist/css/bootstrap.min.css";
import "./App.css";

import Category from "./pages/AddCategoryPage.jsx";
import Log from "./pages/AddExpensePage.jsx";
import Income from "./pages/AddIncomePage.jsx";

function App() {
  const [count, setCount] = useState(0);

  return (
    <>
      {/* <MyNavbar /> */}
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/create/credit" element={<Credit />} />
        <Route path="/create/debit" element={<Debit />} />
        <Route path="/create/category" element={<Category />} />
        <Route path="/create/log" element={<Log />} />
        <Route path="/create/income" element={<Income />} />
      </Routes>
    </>
  );
}

export default App;
