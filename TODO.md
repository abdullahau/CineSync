## TODOs:

- [ ] IMDB (https://datasets.imdbws.com/) `title.ratings.tsv.gz` (averageRating, numVotes), `title.basics.tsv.gz` (genres, runtimeMinutes) (https://developer.imdb.com/non-commercial-datasets/)
- [ ] Figure out an IMDB scraping technique for `?operationName=Title_Storyline` for detailed plot summary, outline, synopses, storylineKeywords, taglines, etc.
- [ ] Figure out a way to scrape IMDB's rating-histogram scraping technique (potentially inside HTML)
- [ ] Ensure that if a title has one person credited with the writer and director role, the name appears on both bills
- [ ] pull `certificate`/`rating` from OMDB API and when wikidata ID or IMDB ID is missing, pull those from OMDB
- [ ] consider adding "to watchlist" to influence recommendation - from Letterboxd or IMDB - optional
- [ ] buzz_window is good, but I want to be able to state where I want something "buzzing" or not.
- [ ] consider adding "certificate/rating" filter to ensure movies are, as per US standards, at maximum of age rating
- [ ] consider creating a quarterly or monthly "wrapped" - like top movies, genres, themes, aesthetic - similar to spotify wrap
- [ ] Rotten Tomato links for each title can be potentially extracted from Wikidata Query SPARQL
- [ ] OMDb (omdb_awards_text and title_score) & Wikipedia (title_awards and detailed_plot) upsert.
- [ ] Candidate pool update cycle (new titles, updates to keywords, scores, plot, etc)
- [ ] Determine where the relationship links between tables in the current schema.sql file (update diagram accordingly)

Sample IMDB response:

```json
{
    "data": {
        "title": {
            "id": "tt0021079",
            "summaries": {
                "edges": [
                    {
                        "node": {
                            "plotText": {
                                "plaidHtml": "Rico is a small-time hood who knocks off gas stations for whatever he can take. He heads east and signs up with Sam Vettori&#39;s mob. A New Year&#39;s Eve robbery at Little Arnie Lorch&#39;s casino results in the death of the new crime commissioner Alvin McClure. Rico&#39;s good friend Joe Massara, who works at the club as a professional dancer, works as the gang&#39;s lookout man and wants out of the gang. Rico is ambitious and eventually takes over Vettori&#39;s gang; he then moves up to the next echelon pushing out Diamond Pete Montana. When he orders Joe to dump his girlfriend Olga and re-join the gang, Olga decides there&#39;s only one way out for them."
                            },
                            "machineTranslatedText": {
                                "language": {
                                    "id": "en-US"
                                },
                                "value": {
                                    "plaidHtml": "Rico is a small-time hood who knocks off gas stations for whatever he can take. He heads east and signs up with Sam Vettori&#39;s mob. A New Year&#39;s Eve robbery at Little Arnie Lorch&#39;s casino results in the death of the new crime commissioner Alvin McClure. Rico&#39;s good friend Joe Massara, who works at the club as a professional dancer, works as the gang&#39;s lookout man and wants out of the gang. Rico is ambitious and eventually takes over Vettori&#39;s gang; he then moves up to the next echelon pushing out Diamond Pete Montana. When he orders Joe to dump his girlfriend Olga and re-join the gang, Olga decides there&#39;s only one way out for them."
                                },
                                "isMachineTranslation": false
                            },
                            "author": "garykmcd"
                        }
                    }
                ]
            },
            "outlines": {
                "edges": [
                    {
                        "node": {
                            "plotText": {
                                "plaidHtml": "A small-time criminal moves to a big city to seek bigger fortune."
                            },
                            "machineTranslatedText": {
                                "language": {
                                    "id": "en-US"
                                },
                                "value": {
                                    "plaidHtml": "A small-time criminal moves to a big city to seek bigger fortune."
                                },
                                "isMachineTranslation": false
                            }
                        }
                    }
                ]
            },
            "synopses": {
                "edges": [
                    {
                        "node": {
                            "plotText": {
                                "plaidHtml": "Small-time Italian-American criminals Caesar Enrico &quot;Rico&quot; Bandello (Edward G. Robinson) and his friend Joe Massara (Douglas Fairbanks, Jr.) move from New York to Chicago to seek their fortunes. Rico joins the gang of Sam Vettori (Stanley Fields), while Joe wants to be a dancer. Olga (Glenda Farrell) becomes his dance partner and girlfriend at the local taxi dance club.<br/><br/>Joe tries to drift away from the gang and its activities including running several speakeasys and illegal gambling casinos, but Rico (whom the gang now refers to by his nickname &#39;Little Caesar&#39;) makes him participate in the robbery of the nightclub where he works. Despite orders from underworld overlord &quot;Big Boy&quot; (Sidney Blackmer) to all his men to avoid bloodshed, Rico guns down crusading police crime commissioner Alvin McClure during the robbery, with Joe as an aghast witness.<br/><br/>Rico accuses Sam of becoming soft and seizes control of his organization. Rival boss &quot;Little Arnie&quot; Storch (Maurice Black) tries to have Rico killed, but Rico is only grazed by a bullet during a drive-by shooting. Rico and his gunmen pay Little Arnie a visit, after which Arnie hastily departs for Detroit. The Big Boy eventually gives Rico control of all of Chicago&#39;s Northside.<br/><br/>Some months later, Rico becomes concerned that Joe knows too much about him. He warns Joe that he must forget about Olga, and join him in a life of crime. Rico threatens to kill both Joe and Olga unless he accedes, but Joe refuses to give in. Olga calls Police Sergeant Flaherty and tells him Joe is ready to talk, just before Rico and his henchman Otero (George E. Stone) come calling. Rico finds, to his surprise, that he is unable to take his friend&#39;s life. When Otero tries to do the job himself, Rico wrestles the gun away from him, though not before Joe is wounded. Hearing the shot, Flaherty and another cop give chase and kill Otero. With the information provided by Joe, Flaherty proceeds to crush Rico&#39;s organization.<br/><br/>Desperate and alone, Rico retreats to the gutter from which he sprang. A few weeks later, while hiding in a flophouse, he becomes enraged when he learns that Flaherty has called him a coward in the newspaper. He foolishly telephones the cop to announce he is coming for him. The call is traced to the phone booth where Rico is. He runs from the police and hides behind a large billboard. Refusing to surrender, Flaherty personally shoots at the billboard with a tommy gun. Ironically, the billboard shows an advertisement featuring dancers Joe and Olga. The police walk around the billboard to find Rico dying on the ground who with his last breath mutters, &quot;Mother of mercy... is this the end of Rico?&quot;"
                            },
                            "machineTranslatedText": {
                                "language": {
                                    "id": "en"
                                },
                                "value": {
                                    "plaidHtml": "Small-time Italian-American criminals Caesar Enrico &quot;Rico&quot; Bandello (Edward G. Robinson) and his friend Joe Massara (Douglas Fairbanks, Jr.) move from New York to Chicago to seek their fortunes. Rico joins the gang of Sam Vettori (Stanley Fields), while Joe wants to be a dancer. Olga (Glenda Farrell) becomes his dance partner and girlfriend at the local taxi dance club.<br/><br/>Joe tries to drift away from the gang and its activities including running several speakeasys and illegal gambling casinos, but Rico (whom the gang now refers to by his nickname &#39;Little Caesar&#39;) makes him participate in the robbery of the nightclub where he works. Despite orders from underworld overlord &quot;Big Boy&quot; (Sidney Blackmer) to all his men to avoid bloodshed, Rico guns down crusading police crime commissioner Alvin McClure during the robbery, with Joe as an aghast witness.<br/><br/>Rico accuses Sam of becoming soft and seizes control of his organization. Rival boss &quot;Little Arnie&quot; Storch (Maurice Black) tries to have Rico killed, but Rico is only grazed by a bullet during a drive-by shooting. Rico and his gunmen pay Little Arnie a visit, after which Arnie hastily departs for Detroit. The Big Boy eventually gives Rico control of all of Chicago&#39;s Northside.<br/><br/>Some months later, Rico becomes concerned that Joe knows too much about him. He warns Joe that he must forget about Olga, and join him in a life of crime. Rico threatens to kill both Joe and Olga unless he accedes, but Joe refuses to give in. Olga calls Police Sergeant Flaherty and tells him Joe is ready to talk, just before Rico and his henchman Otero (George E. Stone) come calling. Rico finds, to his surprise, that he is unable to take his friend&#39;s life. When Otero tries to do the job himself, Rico wrestles the gun away from him, though not before Joe is wounded. Hearing the shot, Flaherty and another cop give chase and kill Otero. With the information provided by Joe, Flaherty proceeds to crush Rico&#39;s organization.<br/><br/>Desperate and alone, Rico retreats to the gutter from which he sprang. A few weeks later, while hiding in a flophouse, he becomes enraged when he learns that Flaherty has called him a coward in the newspaper. He foolishly telephones the cop to announce he is coming for him. The call is traced to the phone booth where Rico is. He runs from the police and hides behind a large billboard. Refusing to surrender, Flaherty personally shoots at the billboard with a tommy gun. Ironically, the billboard shows an advertisement featuring dancers Joe and Olga. The police walk around the billboard to find Rico dying on the ground who with his last breath mutters, &quot;Mother of mercy... is this the end of Rico?&quot;"
                                },
                                "isMachineTranslation": false
                            }
                        }
                    }
                ]
            },
            "storylineKeywords": {
                "edges": [
                    {
                        "node": {
                            "legacyId": "gangster",
                            "text": "gangster"
                        }
                    },
                    {
                        "node": {
                            "legacyId": "organized-crime",
                            "text": "organized crime"
                        }
                    },
                    {
                        "node": {
                            "legacyId": "chicago-illinois",
                            "text": "chicago illinois"
                        }
                    },
                    {
                        "node": {
                            "legacyId": "crime-boss",
                            "text": "crime boss"
                        }
                    },
                    {
                        "node": {
                            "legacyId": "murder",
                            "text": "murder"
                        }
                    }
                ],
                "total": 146
            },
            "taglines": {
                "edges": [
                    {
                        "node": {
                            "text": "His gun was a one-way ticket thru the doorway to hell! (Print Ad- The Standard-Union,((Brooklyn, NY)) 24 January 1931)",
                            "machineTranslatedText": {
                                "language": {
                                    "id": "en-US"
                                },
                                "value": "His gun was a one-way ticket thru the doorway to hell! (Print Ad- The Standard-Union,((Brooklyn, NY)) 24 January 1931)",
                                "isMachineTranslation": false
                            }
                        }
                    }
                ],
                "total": 4
            },
            "genres": {
                "genres": [
                    {
                        "id": "Action",
                        "text": "Action"
                    },
                    {
                        "id": "Crime",
                        "text": "Crime"
                    },
                    {
                        "id": "Drama",
                        "text": "Drama"
                    },
                    {
                        "id": "Romance",
                        "text": "Romance"
                    }
                ]
            },
            "certificate": {
                "rating": "Not Rated",
                "ratingReason": null,
                "ratingsBody": null
            },
            "parentsGuide": {
                "guideItems": {
                    "total": 8
                }
            }
        }
    },
    "extensions": {
        "disclaimer": "Public, commercial, and/or non-private use of the IMDb data provided by this API is not allowed. For limited non-commercial use of IMDb data and the associated requirements see https://help.imdb.com/article/imdb/general-information/can-i-use-imdb-data-in-my-software/G5JTRESSHJBBHTGX#",
        "experimentalFields": {
            "janet": []
        }
    }
}
```