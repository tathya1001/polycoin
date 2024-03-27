import { createContext, useContext, useState, useEffect } from "react";
import { initializeApp } from "firebase/app";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithPopup,
  onAuthStateChanged,
  signOut,
} from "firebase/auth";
import {
  getFirestore,
  collection,
  addDoc,
  getDocs,
  getDoc,
  setDoc,
  doc,
  query,
  where,
  updateDoc,
  serverTimestamp,
} from "firebase/firestore";

import { getStorage, ref, uploadBytes, getDownloadURL } from "firebase/storage";

const FirebaseContext = createContext(null);

const firebaseConfig = {
  apiKey: "AIzaSyCJe8X6Pj4fniPexjesp5OFXfAXxt4-1qA",
  authDomain: "polycoin1001.firebaseapp.com",
  projectId: "polycoin1001",
  storageBucket: "polycoin1001.appspot.com",
  messagingSenderId: "821457758505",
  appId: "1:821457758505:web:cdca7274094434d310ef38",
};

export const useFirebase = () => useContext(FirebaseContext);

const firebaseApp = initializeApp(firebaseConfig);
const firebaseAuth = getAuth(firebaseApp);
const firestore = getFirestore(firebaseApp);
const storage = getStorage(firebaseApp);

const googleProvider = new GoogleAuthProvider();

export const FirebaseProvider = (props) => {
  const [user, setUser] = useState(null);

  useEffect(() => {
    onAuthStateChanged(firebaseAuth, (user) => {
      if (user) setUser(user);
      else setUser(null);
    });
  }, []);

  const signupUserWithEmailAndPassword = (email, password) => {
    try {
      return createUserWithEmailAndPassword(firebaseAuth, email, password);
      // alert("Successfull Register");
    } catch {
      alert("Error while registering. Enter correct credentials.");
    }
  };

  const signinUserWithEmailAndPassword = (email, password) => {
    try {
      signInWithEmailAndPassword(firebaseAuth, email, password);
      alert("Successfull Login");
    } catch {
      alert("Error while login. Enter correct credentials.");
    }
  };

  const signinWithGoogle = () => {
    try {
      signInWithPopup(firebaseAuth, googleProvider);
      alert("Successfull Login");
    } catch {
      alert("Error while login. Enter correct credentials.");
    }
  };

  const handleCreateNewListing = async (name) => {
    return await addDoc(collection(firestore, "users"), {
      name,
      userID: user.uid,
      currencyID: 1,
      totalincome: 0,
      totalexpense: 0,
    });
  };

  const handleNewUser = async (name, userId, currency) => {
    return await setDoc(doc(firestore, "users", userId), {
      name: name,
      userID: userId,
      currency: currency,
      totalincome: 0,
      totalexpense: 0,
    });
  };

  const handleNewCredit = async (name, left, completed, userId) => {
    try {
      await addDoc(collection(firestore, "users", userId, "credit"), {
        name: name,
        left: parseInt(left),
        completed: parseInt(completed),
      });
      alert("Category added successfully");
    } catch {
      alert("Error. Try Again.");
    }
  };

  const handleNewDebit = async (name, left, completed, userId) => {
    try {
      await addDoc(collection(firestore, "users", userId, "debit"), {
        name: name,
        left: parseInt(left),
        completed: parseInt(completed),
      });

      alert("Category added successfully");
    } catch {
      alert("Error. Try Again.");
    }
  };

  const handleNewCategory = async (name, iconid, colorid, userId) => {
    try {
      await addDoc(collection(firestore, "users", userId, "category"), {
        name: name,
        iconid: parseInt(iconid),
        colorid: parseInt(colorid),
        expense: 0,
      });
      alert("Category added successfully");
    } catch {
      alert("Error. Try Again.");
    }
  };

  const handleNewLog = async (
    logName,
    categoryId,
    expense,
    day,
    month,
    year,
    userId
  ) => {
    try {
      await addDoc(collection(firestore, "users", userId, "log"), {
        name: logName,
        categoryid: categoryId,
        transaction: expense,
        day: parseInt(day),
        month: parseInt(month),
        year: parseInt(year),
        timestamp: serverTimestamp(),
      });
      alert("Expense added successfully");
    } catch {
      alert("Error. Try Again.");
    }
  };

  const handleCreditPay = async (
    creditId,
    completed,
    completedAdded,
    userId
  ) => {
    console.log("Credit response given");

    await updateDoc(doc(firestore, "users", userId, "credit", creditId), {
      completed: parseInt(completed) + parseInt(completedAdded),
    });
    console.log("Credit response updated successfully!");

    window.location.reload(); // change this !important
  };

  const handleCreditAdd = async (creditId, left, addition, userId) => {
    console.log("Credit added given");

    await updateDoc(doc(firestore, "users", userId, "credit", creditId), {
      left: parseInt(left) + parseInt(addition),
    });
    console.log("Credit response updated successfully!");

    window.location.reload(); // change this !important
  };

  const handleDebitPay = async (debitId, completed, completedAdded, userId) => {
    console.log("Debit response given");

    await updateDoc(doc(firestore, "users", userId, "debit", debitId), {
      completed: parseInt(completed) + parseInt(completedAdded),
    });
    console.log("Debit response updated successfully!");

    window.location.reload(); // change this !important
  };

  const handleDebitAdd = async (debitId, left, addition, userId) => {
    console.log("Debit added given");

    await updateDoc(doc(firestore, "users", userId, "debit", debitId), {
      left: parseInt(left) + parseInt(addition),
    });
    console.log("Debit response updated successfully!");

    window.location.reload(); // change this !important
  };

  const listAllBooks = () => {
    return getDocs(collection(firestore, "users"));
  };

  const getUserData = async (userId) => {
    try {
      const userDoc = await getDoc(doc(firestore, "users", userId));
      return userDoc.data();
    } catch (error) {
      console.error("Error fetching user data:", error);
      // return null;
    }
  };

  const getCategoryData = async (userId, categoryId) => {
    try {
      const userDoc = await getDoc(
        doc(firestore, "users", userId, "category", categoryId)
      );
      return userDoc.data();
    } catch (error) {
      console.error("Error fetching user data:", error);
      // return null;
    }
  };

  const setCategoryData = async (expense, userId, categoryId) => {
    try {
      const userDoc = await updateDoc(
        doc(firestore, "users", userId, "category", categoryId),
        {
          expense: parseInt(expense),
        }
      );
      // return userDoc.data();
    } catch (error) {
      console.error("Error fetching user data:", error);
      // return null;
    }
  };

  const listAllCredits = (userId) => {
    return getDocs(collection(firestore, "users", userId, "credit"));
  };

  const listAllDebits = (userId) => {
    return getDocs(collection(firestore, "users", userId, "debit"));
  };

  const listAllCategory = (userId) => {
    return getDocs(collection(firestore, "users", userId, "category"));
  };

  const listAllLogs = (userId) => {
    return getDocs(collection(firestore, "users", userId, "log"));
  };

  const getBookById = async (id) => {
    const docRef = doc(firestore, "users", id);
    const result = await getDoc(docRef);
    return result;
  };

  const getImageURL = (path) => {
    return getDownloadURL(ref(storage, path));
  };

  const placeOrder = async (bookId, qty) => {
    const collectionRef = collection(firestore, "users", bookId, "orders");
    const result = await addDoc(collectionRef, {
      userID: user.uid,
      userEmail: user.email,
      displayName: user.displayName,
      photoURL: user.photoURL,
      qty: Number(qty),
    });
    return result;
  };

  const logout = async () => {
    try {
      await signOut(firebaseAuth);
      setUser(null);
    } catch (error) {
      console.error("Error logging out:", error.message);
    }
  };

  const isLoggedIn = user ? true : false;

  return (
    <FirebaseContext.Provider
      value={{
        signinWithGoogle,
        signupUserWithEmailAndPassword,
        signinUserWithEmailAndPassword,
        handleCreateNewListing,
        listAllBooks,
        listAllCredits,
        listAllDebits,
        listAllCategory,
        listAllLogs,
        getImageURL,
        getBookById,
        placeOrder,
        isLoggedIn,
        user,
        handleNewUser,
        handleNewCredit,
        handleNewDebit,
        handleNewCategory,
        handleNewLog,
        // handleCreditResponse,
        handleCreditAdd,
        handleCreditPay,
        handleDebitAdd,
        handleDebitPay,
        logout,
        getUserData,
        getCategoryData,
        setCategoryData,
      }}
    >
      {props.children}
    </FirebaseContext.Provider>
  );
};
