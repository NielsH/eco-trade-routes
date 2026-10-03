//Vehicle cargo capacity and speed, from Eco's AutoGen vehicle sources. Regenerate with: python tools/build_catalog.py
//Modular vehicles (trucks, tractors) get storage from fitted modules: slots/maxWeightKg are null, set them in the page.
window.VEHICLES = {
 "EgyptianCanoe": {
  "slots": 3,
  "maxWeightKg": 400.0,
  "speed": 10.0,
  "water": true
 },
 "IndustrialBarge": {
  "slots": 96,
  "maxWeightKg": 32000.0,
  "speed": 10.0,
  "water": true
 },
 "LargeCanoe": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": true
 },
 "MediumFishingTrawler": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": true
 },
 "NorseCanoe": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": true
 },
 "OnFoot": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 5.0,
  "water": false
 },
 "PoweredCart": {
  "slots": 18,
  "maxWeightKg": 3500.0,
  "speed": 12.0,
  "water": false
 },
 "Scorpion": {
  "slots": 7,
  "maxWeightKg": 7000.0,
  "speed": 14.0,
  "water": false,
  "storages": [
   {
    "Accepts": {
     "OnlyTags": [
      "Wood"
     ]
    }
   }
  ]
 },
 "SmallCanoe": {
  "slots": 3,
  "maxWeightKg": 400.0,
  "speed": 10.0,
  "water": true
 },
 "SmallWoodCart": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": false
 },
 "SmallWoodenBoat": {
  "slots": 18,
  "maxWeightKg": 3500.0,
  "speed": 12.0,
  "water": true
 },
 "SteamTruck": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 18.0,
  "water": false
 },
 "TrailerTruck": {
  "slots": 36,
  "maxWeightKg": 8000.0,
  "speed": 20.0,
  "water": false
 },
 "Truck": {
  "slots": null,
  "maxWeightKg": null,
  "speed": 20.0,
  "water": false
 },
 "Wheelbarrow": {
  "slots": 8,
  "maxWeightKg": 1400.0,
  "speed": 10.0,
  "water": false
 },
 "WoodCart": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 12.0,
  "water": false
 },
 "WoodShopCart": {
  "slots": 12,
  "maxWeightKg": 2100.0,
  "speed": 10.0,
  "water": false
 },
 "WoodenBarge": {
  "slots": 48,
  "maxWeightKg": 10000.0,
  "speed": 10.0,
  "water": true
 },
 "WoodenTransportShip": {
  "slots": 48,
  "maxWeightKg": 14000.0,
  "speed": 10.0,
  "water": true
 }
};
