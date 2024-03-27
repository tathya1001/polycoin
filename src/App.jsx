import { useState } from "react";
import { Routes, Route } from "react-router-dom";

//pages
import Register from "./pages/RegisterNew.jsx";
import Login from "./pages/LoginNew.jsx";
import Home from "./pages/HomeNew.jsx";
import Settings from "./pages/Settings.jsx";
import Credit from "./pages/Credit.jsx";
import Debit from "./pages/Debit.jsx";

import "bootstrap/dist/css/bootstrap.min.css";
import "./App.css";

import Category from "./pages/CategoryNew.jsx";
import Log from "./pages/LogNew.jsx";
import Income from "./pages/Income.jsx";

function App() {
  const [count, setCount] = useState(0);

  return (
    <>
      {/* <MyNavbar /> */}
      <Routes>
        <Route path="/" element={<Home></Home>} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/register" element={<Register></Register>} />
        <Route path="/login" element={<Login></Login>} />
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
