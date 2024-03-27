import React, { useEffect, useState } from "react";

import "./HomePage.css";

import Welcome from "../components/Welcome";
import SampleCard from "../components/SampleCard";
import CategoryCard from "../components/CategoryCard";
import LogCard from "../components/LogCard";
import AddButton from "../components/AddButton";

import { useFirebase } from "../context/Firebase";
import HeroCard from "../components/HeroCard";
import DebitCard from "../components/DebitCard";
import { Navigate } from "react-router-dom";

const Home = () => {
  const firebase = useFirebase();

  const [books, setBooks] = useState([]);
  const [credits, setCredits] = useState([]);
  const [debits, setDebits] = useState([]);
  const [categories, setCategories] = useState([]);
  const [logs, setLogs] = useState([]);
  const [totalTransactions, setTotalTransactions] = useState(0);
  const [totalExpense, setTotalExpense] = useState(0);
  const [totalIncome, setTotalIncome] = useState(0);
  // const [totalTransactions, setTotalTransactions] = useState(0);

  useEffect(() => {
    firebase.listAllBooks().then((books) => setBooks(books.docs));
  }, []);

  //listing

  useEffect(() => {
    if (firebase.user) {
      firebase
        .listAllCredits(firebase.user.uid)
        .then((credit) => setCredits(credit.docs));
    }
  }, [firebase.user]);

  useEffect(() => {
    if (firebase.user) {
      firebase
        .listAllDebits(firebase.user.uid)
        .then((debit) => setDebits(debit.docs));
    }
  }, [firebase.user]);

  useEffect(() => {
    if (firebase.user) {
      firebase
        .listAllCategory(firebase.user.uid)
        .then((category) => setCategories(category.docs));
    }
  }, [firebase.user]);

  useEffect(() => {
    if (firebase.user) {
      const fetchLogs = async () => {
        const logsData = await firebase.listAllLogs(firebase.user.uid);
        setLogs(logsData.docs);

        // Calculate total transaction value
        let total = 0;
        logsData.docs.forEach((log) => {
          if (log.data().categoryid == 1) {
            total += parseInt(log.data().transaction);
          }
        });
        setTotalIncome(total);

        total = 0;
        logsData.docs.forEach((log) => {
          if (log.data().categoryid != 1) {
            total += parseInt(log.data().transaction);
          }
        });
        setTotalExpense(total);

        // setLogs(logsData.sort((a, b) => b.timestamp - a.timestamp));
      };

      fetchLogs();
    }
  }, [firebase.user]);

  if (!firebase.user) {
    return <Navigate to="/login" />; // Redirect the user to the login page
  }

  //for horizontal scrolling
  useEffect(() => {
    const container = document.querySelector(".credit-section");

    const handleScroll = (event) => {
      container.scrollLeft += event.deltaY * 0.5;
      event.preventDefault();
    };

    container.addEventListener("wheel", handleScroll);

    return () => {
      container.removeEventListener("wheel", handleScroll);
    };
  }, []);

  useEffect(() => {
    const container = document.querySelector(".category-section");

    const handleScroll = (event) => {
      container.scrollLeft += event.deltaY * 0.5;
      event.preventDefault();
    };

    container.addEventListener("wheel", handleScroll);

    return () => {
      container.removeEventListener("wheel", handleScroll);
    };
  }, []);

  useEffect(() => {
    const container = document.querySelector(".debit-section");

    const handleScroll = (event) => {
      container.scrollLeft += event.deltaY * 0.5;
      event.preventDefault();
    };

    container.addEventListener("wheel", handleScroll);

    return () => {
      container.removeEventListener("wheel", handleScroll);
    };
  }, []);

  //get user data

  const [userName, setUserName] = useState("");

  useEffect(() => {
    if (firebase.user) {
      const fetchUserData = async () => {
        const userData = await firebase.getUserData(firebase.user.uid);
        if (userData) {
          setUserName(userData.name);
        }
      };

      fetchUserData();
    }
  }, [firebase.user]);

  const [currency, setCurrency] = useState("");
  useEffect(() => {
    if (firebase.user) {
      const fetchUserData = async () => {
        const userData = await firebase.getUserData(firebase.user.uid);
        if (userData) {
          setUserName(userData.name);
        }
      };

      fetchUserData();
    }
  }, [firebase.user]);

  return (
    <div className="flex">
      <div className="bg-[#05051f] min-h-screen min-w-screen p-3 md:p-4 grid grid-cols-12 font-[Rubik] gap-3 w-screen">
        <div className="flex flex-col col-span-12 lg:col-span-9">
          <Welcome name={userName}></Welcome>

          <div className="flex gap-2 columns-2 w-full flex-row">
            <HeroCard
              title={"Expense"}
              trans={totalExpense}
              color={""}
            ></HeroCard>
            <HeroCard
              title={"Income"}
              trans={totalIncome}
              color={""}
            ></HeroCard>
          </div>

          <h3 className="font-normal mt-4 text-white opacity-35 text-2xl">
            Categories
          </h3>

          <div className="category-section space-x-2 flex overflow-x-auto overflow-hidden">
            <AddButton link="/create/category" height={"12rem"}></AddButton>
            {categories.map((cate) => (
              <CategoryCard
                key={cate.id}
                link={`/book/view/${cate.id}`}
                id={cate.id}
                {...cate.data()}
              />
            ))}
          </div>

          <h3 className="font-normal mt-4 text-white opacity-35 text-2xl">
            Credit
          </h3>

          <div className="credit-section space-x-2 flex overflow-x-auto overflow-hidden">
            <AddButton link="/create/credit" height={"6rem"}></AddButton>
            {credits.map((creds) => (
              <SampleCard
                key={creds.id}
                link={`/book/view/${creds.id}`}
                id={creds.id}
                {...creds.data()}
              />
            ))}
          </div>

          <h3 className="font-normal mt-4 text-white opacity-35 text-2xl">
            Debit
          </h3>

          <div className="debit-section space-x-2 flex overflow-x-auto overflow-hidden">
            <AddButton link="/create/debit" height={"6rem"}></AddButton>
            {debits.map((debs) => (
              <DebitCard
                key={debs.id}
                link={`/book/view/${debs.id}`}
                id={debs.id}
                {...debs.data()}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-col h-[45rem] col-span-12 lg:col-span-3 gap-2">
          <h3 className="font-normal text-white opacity-35 text-2xl m-0">
            Expense History
          </h3>

          <AddButton link="/create/log" height={"4rem"}></AddButton>

          <div className="flex flex-col gap-2 overflow-y-auto overflow-x-hidden overflow-hidden scrollbar-hide columns-2">
            {logs
              .slice() // Create a copy of the logs array to avoid mutating the original array
              .sort((a, b) => b.data().timestamp - a.data().timestamp) // Sort the logs array based on timestamp
              .map((log) => (
                <LogCard
                  key={log.id}
                  link={`/book/view/${log.id}`}
                  id={log.id}
                  {...log.data()}
                />
              ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home;
