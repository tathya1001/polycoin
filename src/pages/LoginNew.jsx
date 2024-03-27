import React, { useState, useEffect } from "react";
import Form from "react-bootstrap/Form";
import { useFirebase } from "../context/Firebase";

import { useNavigate } from "react-router-dom";

function Login() {
  const firebase = useFirebase();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (firebase.isLoggedIn) {
      // navigate to home
      navigate("/");
    }
  }, [firebase, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    console.log("Loging in");
    const result = await firebase.signinUserWithEmailAndPassword(
      email,
      password
    );
    console.log("Successfull", result);
  };

  return (
    <div className="bg-slate-900">
      <div
        className="container flex flex-col justify-center items-center h-svh font-[Rubik]"
        onSubmit={handleSubmit}
      >
        <h2 className="text-white mb-4 ">Login</h2>
        <Form className="columns-md flex-col space-y-3 ">
          <div className="relative">
            <input
              type="email"
              id="floating_outlined2"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setEmail(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Email
            </label>
          </div>

          <div className="relative">
            <input
              type="password"
              id="floating_outlined3"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setPassword(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Password
            </label>
          </div>

          <button
            type="submit"
            className="w-full bg-white text-slate-900 focus:ring-4 focus:outline-none focus:ring-blue-300 dark:focus:ring-blue-800 shadow-lg shadow-blue-500/50 dark:shadow-lg dark:shadow-blue-800/80 font-medium rounded-lg text-md px-5 py-2.5 text-center me-2 mb-2 transition-all duration-300 ease-in-out"
          >
            Submit
          </button>
          {/* <button
            disabled
            type="button"
            class="text-white w-full flex m-0 select-none justify-center items-center font-medium rounded-lg text-md px-2.5 pb-2.5 pt-2.5 text-center"
            onClick={firebase.signinWithGoogle}
          >
            OR
          </button>

          <button
            type="button"
            class="text-white w-full flex justify-center items-center bg-[#4285F4] hover:bg-[#4285F4]/90 focus:ring-4 focus:outline-none focus:ring-[#4285F4]/50 font-medium rounded-lg text-md px-2.5 pb-2.5 pt-2.5 text-center dark:focus:ring-[#4285F4]/55 me-2 mb-2"
            onClick={firebase.signinWithGoogle}
          >
            <svg
              class="w-4 h-4 me-2"
              aria-hidden="true"
              xmlns="http://www.w3.org/2000/svg"
              fill="currentColor"
              viewBox="0 0 18 19"
            >
              <path
                fill-rule="evenodd"
                d="M8.842 18.083a8.8 8.8 0 0 1-8.65-8.948 8.841 8.841 0 0 1 8.8-8.652h.153a8.464 8.464 0 0 1 5.7 2.257l-2.193 2.038A5.27 5.27 0 0 0 9.09 3.4a5.882 5.882 0 0 0-.2 11.76h.124a5.091 5.091 0 0 0 5.248-4.057L14.3 11H9V8h8.34c.066.543.095 1.09.088 1.636-.086 5.053-3.463 8.449-8.4 8.449l-.186-.002Z"
                clip-rule="evenodd"
              />
            </svg>
            Sign in with Google
          </button> */}

          <p className="text-slate-400">
            Already having an account?{" "}
            <a
              href="/register"
              className="text-blue-400 decoration-transparent font-semibold"
            >
              Register
            </a>
          </p>
        </Form>
      </div>
    </div>
  );
}

export default Login;
